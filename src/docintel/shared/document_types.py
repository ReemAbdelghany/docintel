"""Types shared by the models, schemas and components."""

from dataclasses import dataclass
from enum import StrEnum


class DocumentType(StrEnum):
    INVOICE = "invoice"
    CONTRACT = "contract"
    OTHER = "other"


class DocumentStatus(StrEnum):
    PROCESSING = "processing"
    ACCEPTED = "accepted"
    REJECTED = "rejected"  # readable, but fails the business rules
    NEEDS_REVIEW = "needs_review"  # the system could not process it with confidence


@dataclass(frozen=True, slots=True)
class ParsedPage:
    number: int
    text: str
