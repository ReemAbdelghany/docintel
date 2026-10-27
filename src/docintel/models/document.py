"""Database tables (SQLModel): cases and documents.

This module defines the SQLModel classes that map to the PostgreSQL database
tables for the document intelligence service. These are the ORM models used
for database operations - they are never returned directly from API endpoints
(use the schemas in routers/v1alpha1/schemas/document.py instead).

Tables:
- cases: Onboarding applications (one per SME)
- documents: Uploaded files with processing results

The documents table uses JSONB columns for flexible storage of structured
extraction results (facts, evidence, findings) while maintaining queryability
for key fields (status, document_type, case_id).
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel

from docintel.shared.document_types import DocumentStatus


def utcnow() -> datetime:
    """Get current UTC timestamp.

    Returns:
        datetime: Current time in UTC with timezone info.
    """
    return datetime.now(UTC)


class Case(SQLModel, table=True):
    """One SME's onboarding application.

    A case is a container for all documents uploaded during a single SME
    onboarding session. It has minimal fields - just an ID and creation timestamp.

    Attributes:
        id: Primary key, auto-generated UUID.
        created_at: Timestamp when the case was created (UTC).
    """

    __tablename__ = "cases"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True)))


class Document(SQLModel, table=True):
    """An uploaded file and everything the pipeline decided about it.

    Stores the raw file reference (storage_uri, content_hash for deduplication)
    and all pipeline outputs: classification, extraction, verification findings,
    and final decision.

    JSONB columns (findings, facts, evidence) store structured data that varies
    by document type while keeping the schema flexible.

    Attributes:
        id: Primary key, auto-generated UUID.
        case_id: Foreign key to cases table, indexed.
        filename: Original uploaded filename.
        content_hash: SHA-256 hex digest of file content (for deduplication).
        storage_uri: URI where raw file is stored (local:// or s3://).
        status: Pipeline outcome (processing/accepted/rejected/needs_review).
        document_type: Classified type (invoice/contract/other).
        classification_confidence: Classification confidence score (0.0-1.0).
        reason: Human-readable reason for rejection or review.
        findings: List of validation findings (JSONB).
        facts: Extracted facts as JSON (InvoiceFacts or ContractFacts).
        evidence: Grounded evidence quotes with page numbers (JSONB).
        model: LLM model specification used for extraction.
        created_at: Document creation timestamp (UTC).
        updated_at: Last update timestamp (UTC).
    """

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("case_id", "content_hash"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    case_id: UUID = Field(foreign_key="cases.id", index=True)
    filename: str
    content_hash: str
    storage_uri: str
    status: str = Field(default=DocumentStatus.PROCESSING, index=True)
    document_type: str | None = None
    classification_confidence: float | None = None
    reason: str | None = None  # why it was rejected or sent to review
    findings: list[dict[str, str]] = Field(default_factory=list, sa_column=Column(JSONB))
    facts: dict[str, object] | None = Field(default=None, sa_column=Column(JSONB))
    evidence: list[dict[str, object]] = Field(default_factory=list, sa_column=Column(JSONB))
    model: str | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True)))
