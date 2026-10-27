"""DocumentAnalysis: the aggregate root of the Understanding context."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from docintel.models.errors import IllegalTransition, InvariantViolated
from docintel.models.events import (
    AnalysisAccepted,
    AnalysisFailed,
    DocumentParsed,
    DomainEvent,
    ExtractionCompleted,
    ReviewRequested,
)
from docintel.models.facts import Facts
from docintel.models.states import ALLOWED, DocumentStatus
from docintel.models.values import Confidence, DocumentType, Evidence


class Severity(StrEnum):
    BLOCKING = "blocking"
    ADVISORY = "advisory"


@dataclass(frozen=True, slots=True)
class Finding:
    """A rule violation or doubt about an extraction."""

    code: str
    severity: Severity
    field: str | None = None
    message: str = ""

    @property
    def blocking(self) -> bool:
        return self.severity is Severity.BLOCKING


@dataclass(frozen=True, slots=True)
class Provenance:
    """Which model, prompt and schema produced an extraction, and what it cost."""

    model: str
    prompt_version: str
    schema_version: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class Extraction:
    version: int
    facts: Facts
    evidence: tuple[Evidence, ...]
    provenance: Provenance

    def missing_evidence(self) -> list[str]:
        """Required facts that have a value but no supporting evidence."""
        have = {e.field for e in self.evidence}
        return [
            f for f in self.facts.REQUIRED if getattr(self.facts, f) is not None and f not in have
        ]


class DocumentAnalysis:
    """The system's work on one submitted document, from parsing to a decision.

    Every state change goes through a method that enforces the invariants:
    allowed transitions only, no acceptance with a blocking finding, evidence
    for every required fact, and re-extraction keeps earlier versions.
    """

    def __init__(self, document_id: UUID, case_id: UUID, filename: str, storage_uri: str) -> None:
        self.document_id, self.case_id = document_id, case_id
        self.filename, self.storage_uri = filename, storage_uri
        self.status = DocumentStatus.RECEIVED
        self.parsed_uri: str | None = None
        self.document_type: DocumentType | None = None
        self.classification_confidence: Confidence | None = None
        self.extractions: list[Extraction] = []
        self.findings: list[Finding] = []
        self._events: list[DomainEvent] = []

    def _move(self, to: DocumentStatus) -> None:
        if to not in ALLOWED[self.status]:
            raise IllegalTransition(f"{self.status} -> {to}")
        self.status = to

    def record_parse(self, parsed_uri: str) -> None:
        """Record that parsing finished and where the parsed document is stored."""
        self._move(DocumentStatus.PARSED)
        self.parsed_uri = parsed_uri
        self._events.append(DocumentParsed(self.document_id))

    def classify(self, doc_type: DocumentType, confidence: Confidence) -> None:
        self._move(DocumentStatus.CLASSIFIED)
        self.document_type, self.classification_confidence = doc_type, confidence

    def record_extraction(
        self, facts: Facts, evidence: tuple[Evidence, ...], provenance: Provenance
    ) -> None:
        self._move(DocumentStatus.EXTRACTED)
        version = len(self.extractions) + 1
        self.extractions.append(Extraction(version, facts, evidence, provenance))
        self._events.append(ExtractionCompleted(self.document_id, version))

    def record_verification(self, findings: list[Finding]) -> None:
        self._move(DocumentStatus.VALIDATED)
        self.findings = findings

    def accept(self) -> None:
        if any(f.blocking for f in self.findings):
            raise InvariantViolated("cannot accept with blocking findings")
        if self.current.missing_evidence():
            raise InvariantViolated("required facts have no evidence")
        self._move(DocumentStatus.ACCEPTED)
        self._events.append(AnalysisAccepted(self.document_id, self.current.version))

    def request_review(self, reasons: list[str]) -> None:
        self._move(DocumentStatus.NEEDS_REVIEW)
        self._events.append(ReviewRequested(self.document_id, tuple(reasons)))

    def fail(self, reason: str) -> None:
        self._move(DocumentStatus.FAILED)
        self._events.append(AnalysisFailed(self.document_id, reason))

    def reprocess(self) -> None:
        """Re-run from classification. Keeps the parse and every earlier extraction."""
        self._move(DocumentStatus.CLASSIFIED)
        self.findings = []

    @property
    def current(self) -> Extraction:
        if not self.extractions:
            raise InvariantViolated("no extraction recorded yet")
        return self.extractions[-1]

    def pull_events(self) -> list[DomainEvent]:
        events, self._events = self._events, []
        return events
