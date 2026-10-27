"""Read-side views: plain data answering a GET without loading aggregates."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FindingView:
    code: str
    severity: str
    field: str | None
    message: str


@dataclass(frozen=True, slots=True)
class DocumentStatusView:
    document_id: UUID
    case_id: UUID
    filename: str
    status: str
    document_type: str | None
    classification_confidence: float | None
    findings: tuple[FindingView, ...]


@dataclass(frozen=True, slots=True)
class EvidenceView:
    field: str
    page: int
    snippet: str


@dataclass(frozen=True, slots=True)
class DocumentResultView:
    document_id: UUID
    status: str
    document_type: str | None
    version: int
    facts: dict[str, object]
    evidence: tuple[EvidenceView, ...]
    model: str
    prompt_version: str
    schema_version: str


class Queries(Protocol):
    async def document_status(self, document_id: UUID) -> DocumentStatusView: ...
    async def document_result(self, document_id: UUID) -> DocumentResultView: ...
