from uuid import UUID

from pydantic import BaseModel


class UploadResponse(BaseModel):
    document_id: UUID
    duplicate: bool
    status_url: str


class FindingResponse(BaseModel):
    code: str
    severity: str
    field: str | None
    message: str


class DocumentStatusResponse(BaseModel):
    document_id: UUID
    case_id: UUID
    filename: str
    status: str
    document_type: str | None
    classification_confidence: float | None
    findings: list[FindingResponse]


class EvidenceResponse(BaseModel):
    field: str
    page: int
    snippet: str


class DocumentResultResponse(BaseModel):
    document_id: UUID
    status: str
    document_type: str | None
    version: int
    facts: dict[str, object]
    evidence: list[EvidenceResponse]
    model: str
    prompt_version: str
    schema_version: str
