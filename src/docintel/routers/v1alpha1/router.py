"""FastAPI router for the document intelligence API v1alpha1.

This module defines the REST API endpoints for the document intelligence service.
All endpoints are versioned under the /v1alpha1 prefix.

Endpoints:
- POST /cases: Create a new onboarding case
- POST /cases/{case_id}/documents: Upload a document for processing
- GET /documents/{document_id}: Get document status and extraction results
- GET /cases/{case_id}/documents: List all documents for a case (testing)
- POST /documents/{document_id}/reprocess: Re-run the pipeline (testing)

The upload endpoint returns 202 Accepted immediately and processes the document
in a background task. Clients poll the status URL to get results.
"""

import hashlib
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile

from docintel.config import BASE_URL_PREFIX, get_settings
from docintel.models.document import Document
from docintel.routers.v1alpha1.components import crud
from docintel.routers.v1alpha1.components.document_processor import process_document
from docintel.routers.v1alpha1.schemas.document import (
    CaseResponse,
    DocumentResponse,
    FieldEvidence,
    Finding,
    UploadResponse,
)
from docintel.utils.providers.storage_provider import get_storage

v1alpha1_router = APIRouter(prefix=BASE_URL_PREFIX)


def to_response(document: Document) -> DocumentResponse:
    """Convert a database Document model to an API response schema.

    Transforms the internal SQLModel Document (with JSONB fields) into the
    Pydantic DocumentResponse schema used by the API.

    Args:
        document: Database document model.

    Returns:
        DocumentResponse: API response schema with typed fields.
    """
    return DocumentResponse(
        document_id=document.id,
        case_id=document.case_id,
        filename=document.filename,
        status=document.status,
        document_type=document.document_type,
        classification_confidence=document.classification_confidence,
        reason=document.reason,
        findings=[Finding(**f) for f in document.findings],
        facts=document.facts,
        evidence=[FieldEvidence(**e) for e in document.evidence],  # type: ignore[arg-type,unused-ignore]
        model=document.model,
    )


async def _document_or_404(document_id: UUID) -> Document:
    """Fetch a document by ID or raise 404.

    Args:
        document_id: UUID of the document to fetch.

    Returns:
        Document: The database document model.

    Raises:
        HTTPException: 404 if document not found.
    """
    document = await crud.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"document {document_id} not found")
    return document


@v1alpha1_router.post("/cases", status_code=201, tags=["cases"])
async def create_case() -> CaseResponse:
    """Create a new onboarding case.

    A case is a container for documents belonging to a single SME onboarding
    application. Returns the case ID for subsequent document uploads.

    Returns:
        CaseResponse: Contains the newly created case_id.
    """
    return CaseResponse(case_id=(await crud.create_case()).id)


@v1alpha1_router.post("/cases/{case_id}/documents", status_code=202, tags=["documents"])
async def upload_document(
    case_id: UUID, file: UploadFile, background: BackgroundTasks
) -> UploadResponse:
    """Upload a document for asynchronous processing.

    Accepts a PDF or image file, stores it content-addressed (SHA-256), and
    queues the full processing pipeline (parse -> classify -> extract -> verify)
    as a background task. Returns immediately with 202 Accepted.

    Deduplication: If the same file content (by SHA-256) was already uploaded
    to this case, returns the existing document without re-processing.

    Args:
        case_id: UUID of the case to attach the document to.
        file: Uploaded file (PDF, PNG, JPG, JPEG, TIFF).
        background: FastAPI background tasks for async processing.

    Returns:
        UploadResponse: Document ID, duplicate flag, initial status, and
            status URL for polling.

    Raises:
        HTTPException: 404 if case not found, 422 if file empty, 413 if file
            exceeds max_upload_bytes setting.
    """
    if await crud.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail=f"case {case_id} not found")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="the file is empty")
    if len(content) > get_settings().max_upload_bytes:
        raise HTTPException(status_code=413, detail="the file is too large")
    digest = hashlib.sha256(content).hexdigest()
    uri = await get_storage().put(f"raw/{case_id}/{digest}", content)  # content-addressed
    document, created = await crud.add_document(case_id, file.filename or "unnamed", digest, uri)
    if created:
        background.add_task(process_document, document.id)
    return UploadResponse(
        document_id=document.id,
        duplicate=not created,
        status=document.status,
        status_url=f"{BASE_URL_PREFIX}/documents/{document.id}",
    )


@v1alpha1_router.get("/documents/{document_id}", tags=["documents"])
async def get_document(document_id: UUID) -> DocumentResponse:
    """Get the processing status and results for a document.

    Returns the current status (processing/accepted/rejected/needs_review),
    document type, classification confidence, extracted facts, evidence quotes,
    and any findings (warnings, errors, derived values).

    Args:
        document_id: UUID of the document to retrieve.

    Returns:
        DocumentResponse: Complete document status and extraction results.

    Raises:
        HTTPException: 404 if document not found.
    """
    return to_response(await _document_or_404(document_id))


@v1alpha1_router.get("/cases/{case_id}/documents", tags=["testing"])
async def list_documents(case_id: UUID) -> list[DocumentResponse]:
    """List all documents for a case (testing endpoint).

    Returns all documents belonging to a case, ordered by creation time.
    Tagged as "testing" - not intended for production use.

    Args:
        case_id: UUID of the case.

    Returns:
        list[DocumentResponse]: All documents in the case.
    """
    return [to_response(d) for d in await crud.list_documents(case_id)]


@v1alpha1_router.post("/documents/{document_id}/reprocess", status_code=202, tags=["testing"])
async def reprocess_document(document_id: UUID, background: BackgroundTasks) -> DocumentResponse:
    """Re-run the processing pipeline for a document (testing endpoint).

    Resets the document to PROCESSING state, clears all previous extraction
    results, and queues a fresh pipeline run. Useful after provider outages
    or configuration changes.

    Tagged as "testing" - not intended for production use.

    Args:
        document_id: UUID of the document to reprocess.
        background: FastAPI background tasks for async processing.

    Returns:
        DocumentResponse: Document with status reset to PROCESSING.

    Raises:
        HTTPException: 404 if document not found.
    """
    await _document_or_404(document_id)
    await crud.mark_processing(document_id)
    background.add_task(process_document, document_id)
    return to_response(await _document_or_404(document_id))
