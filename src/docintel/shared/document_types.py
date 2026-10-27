"""Shared type definitions for the document intelligence service.

This module contains core type definitions used across models, schemas, and
processing components. Using shared types ensures consistency between the
database layer, API schemas, and processing pipeline.

Types:
- DocumentType: Classification categories for business documents
- DocumentStatus: Processing pipeline outcome states
- ParsedPage: Single page of extracted text with page number
"""

from dataclasses import dataclass
from enum import StrEnum


class DocumentType(StrEnum):
    """Classification categories for business documents.

    Values are lowercase strings for API serialization compatibility.
    """

    INVOICE = "invoice"
    CONTRACT = "contract"
    OTHER = "other"


class DocumentStatus(StrEnum):
    """Processing pipeline outcome states.

    Represents the final disposition of a document after processing:
    - PROCESSING: Document is currently being processed (transient state)
    - ACCEPTED: Confident extraction, all business rules pass
    - REJECTED: Document is readable but fails business rules (wrong type, rule violation)
    - NEEDS_REVIEW: Parsing, classification, or extraction failed/unsure; missing facts;
      quotes not found in document; or provider unavailable
    """

    PROCESSING = "processing"
    ACCEPTED = "accepted"
    REJECTED = "rejected"  # readable, but fails the business rules
    NEEDS_REVIEW = "needs_review"  # the system could not process it with confidence


@dataclass(frozen=True, slots=True)
class ParsedPage:
    """A single page of parsed document text.

    Represents one page of extracted text from a document, with its page number.
    Used as the input to classification and extraction steps, and for evidence
    grounding (quotes must reference a specific page).

    Attributes:
        number: 1-based page number in the document.
        text: Extracted text content from the page (may be empty for blank pages).
    """

    number: int
    text: str
