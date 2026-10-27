"""Database tables (SQLModel): a case and the documents uploaded to it."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel

from docintel.shared.document_types import DocumentStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class Case(SQLModel, table=True):
    """One SME's onboarding application."""

    __tablename__ = "cases"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True)))


class Document(SQLModel, table=True):
    """An uploaded file and everything the pipeline decided about it."""

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
