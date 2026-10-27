"""The document state machine, expressed as data."""

from enum import StrEnum


class DocumentStatus(StrEnum):
    RECEIVED = "received"
    PARSED = "parsed"
    CLASSIFIED = "classified"
    EXTRACTED = "extracted"
    VALIDATED = "validated"
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"
    FAILED = "failed"


S = DocumentStatus

ALLOWED: dict[DocumentStatus, set[DocumentStatus]] = {
    S.RECEIVED: {S.PARSED, S.FAILED},
    S.PARSED: {S.CLASSIFIED, S.FAILED},
    S.CLASSIFIED: {S.EXTRACTED, S.FAILED},
    S.EXTRACTED: {S.VALIDATED, S.FAILED},
    S.VALIDATED: {S.ACCEPTED, S.NEEDS_REVIEW, S.FAILED},
    S.NEEDS_REVIEW: {S.ACCEPTED, S.REJECTED, S.CLASSIFIED},  # CLASSIFIED = reprocess
    S.ACCEPTED: {S.CLASSIFIED},  # reprocess only
    S.REJECTED: {S.CLASSIFIED},
    S.FAILED: {S.RECEIVED, S.CLASSIFIED},  # manual retry
}
