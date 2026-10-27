from uuid import UUID

from fastapi import APIRouter, UploadFile

from docintel.routers.dependencies import ContainerDep
from docintel.routers.v1alpha1.schemas.documents import (
    DocumentResultResponse,
    DocumentStatusResponse,
    EvidenceResponse,
    FindingResponse,
    UploadResponse,
)

router = APIRouter(tags=["documents"])


@router.post("/cases/{case_id}/documents", status_code=202)
async def upload_document(case_id: UUID, file: UploadFile, c: ContainerDep) -> UploadResponse:
    result = await c.submit_document(case_id, file.filename or "unnamed", await file.read())
    return UploadResponse(
        document_id=result.document_id,
        duplicate=result.duplicate,
        status_url=f"/v1alpha1/documents/{result.document_id}",
    )


@router.get("/documents/{document_id}")
async def get_document(document_id: UUID, c: ContainerDep) -> DocumentStatusResponse:
    view = await c.queries.document_status(document_id)
    return DocumentStatusResponse(
        document_id=view.document_id,
        case_id=view.case_id,
        filename=view.filename,
        status=view.status,
        document_type=view.document_type,
        classification_confidence=view.classification_confidence,
        findings=[
            FindingResponse(code=f.code, severity=f.severity, field=f.field, message=f.message)
            for f in view.findings
        ],
    )


@router.get("/documents/{document_id}/result")
async def get_result(document_id: UUID, c: ContainerDep) -> DocumentResultResponse:
    view = await c.queries.document_result(document_id)
    return DocumentResultResponse(
        document_id=view.document_id,
        status=view.status,
        document_type=view.document_type,
        version=view.version,
        facts=view.facts,
        evidence=[
            EvidenceResponse(field=e.field, page=e.page, snippet=e.snippet) for e in view.evidence
        ],
        model=view.model,
        prompt_version=view.prompt_version,
        schema_version=view.schema_version,
    )
