"""OnboardingCase: the Intake aggregate. Receives documents and rejects duplicates."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from docintel.models.errors import InvariantViolated
from docintel.models.events import DocumentSubmitted, DomainEvent


@dataclass(frozen=True, slots=True)
class SubmittedDocument:
    id: UUID
    filename: str
    content_hash: str
    storage_uri: str


class OnboardingCase:
    """One SME's onboarding application.

    Invariants: no two submissions with the same content hash, and a closed
    case accepts no new submissions.
    """

    def __init__(self, case_id: UUID) -> None:
        self.case_id = case_id
        self.closed = False
        self._documents: dict[str, SubmittedDocument] = {}
        self._events: list[DomainEvent] = []

    @property
    def documents(self) -> list[SubmittedDocument]:
        return list(self._documents.values())

    def submit(
        self, filename: str, content_hash: str, storage_uri: str
    ) -> tuple[SubmittedDocument, bool]:
        """Add a document. Returns it and whether it is new; a duplicate returns the original."""
        if self.closed:
            raise InvariantViolated("case is closed")
        existing = self._documents.get(content_hash)
        if existing is not None:
            return existing, False
        document = SubmittedDocument(uuid4(), filename, content_hash, storage_uri)
        self._documents[content_hash] = document
        self._events.append(
            DocumentSubmitted(
                document_id=document.id,
                case_id=self.case_id,
                filename=filename,
                storage_uri=storage_uri,
            )
        )
        return document, True

    def restore(self, document: SubmittedDocument) -> None:
        """Rebuild state from storage without raising events."""
        self._documents[document.content_hash] = document

    def close(self) -> None:
        self.closed = True

    def pull_events(self) -> list[DomainEvent]:
        events, self._events = self._events, []
        return events
