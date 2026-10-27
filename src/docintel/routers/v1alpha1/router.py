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
    document = await crud.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"document {document_id} not found")
    return document


@v1alpha1_router.post("/cases", status_code=201, tags=["cases"])
async def create_case() -> CaseResponse:
    """Create an onboarding case to upload documents to."""
    return CaseResponse(case_id=(await crud.create_case()).id)


@v1alpha1_router.post("/cases/{case_id}/documents", status_code=202, tags=["documents"])
async def upload_document(
    case_id: UUID, file: UploadFile, background: BackgroundTasks
) -> UploadResponse:
    """Upload a PDF or image. It is parsed, classified, extracted and decided in the background."""
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
    """Status, decision, extracted facts and evidence for one document."""
    return to_response(await _document_or_404(document_id))


@v1alpha1_router.get("/cases/{case_id}/documents", tags=["testing"])
async def list_documents(case_id: UUID) -> list[DocumentResponse]:
    """Every document of a case (for testing)."""
    return [to_response(d) for d in await crud.list_documents(case_id)]


@v1alpha1_router.post("/documents/{document_id}/reprocess", status_code=202, tags=["testing"])
async def reprocess_document(document_id: UUID, background: BackgroundTasks) -> DocumentResponse:
    """Run the pipeline again, for example after a provider outage (for testing)."""
    await _document_or_404(document_id)
    await crud.mark_processing(document_id)
    background.add_task(process_document, document_id)
    return to_response(await _document_or_404(document_id))
