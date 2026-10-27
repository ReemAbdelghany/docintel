"""Domain events: something that happened inside the Understanding context."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DomainEvent:
    document_id: UUID


@dataclass(frozen=True, slots=True)
class DocumentParsed(DomainEvent):
    pass


@dataclass(frozen=True, slots=True)
class ExtractionCompleted(DomainEvent):
    version: int


@dataclass(frozen=True, slots=True)
class AnalysisAccepted(DomainEvent):
    version: int


@dataclass(frozen=True, slots=True)
class ReviewRequested(DomainEvent):
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalysisFailed(DomainEvent):
    reason: str
