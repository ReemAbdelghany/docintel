"""SQLAlchemy rows: persistence shapes for all three contexts, one metadata object for Alembic."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Json = dict[str, object]


class Base(DeclarativeBase):
    pass


class CaseRow(Base):
    __tablename__ = "cases"
    case_id: Mapped[UUID] = mapped_column(primary_key=True)
    closed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SubmittedDocumentRow(Base):
    __tablename__ = "submitted_documents"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.case_id"), index=True)
    content_hash: Mapped[str]
    filename: Mapped[str]
    storage_uri: Mapped[str]
    __table_args__ = (UniqueConstraint("case_id", "content_hash"),)


class AnalysisRow(Base):
    __tablename__ = "analyses"
    document_id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(index=True)
    filename: Mapped[str]
    storage_uri: Mapped[str]
    parsed_uri: Mapped[str | None]
    status: Mapped[str] = mapped_column(index=True)
    document_type: Mapped[str | None]
    classification_confidence: Mapped[float | None]
    findings: Mapped[list[Json]] = mapped_column(JSONB, default=list)
    version: Mapped[int] = mapped_column(default=1)
    __mapper_args__ = {"version_id_col": version}  # optimistic concurrency


class ExtractionRow(Base):
    __tablename__ = "extractions"
    document_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.document_id"), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    facts_type: Mapped[str]
    facts: Mapped[Json] = mapped_column(JSONB)
    evidence: Mapped[list[Json]] = mapped_column(JSONB)
    provenance: Mapped[Json] = mapped_column(JSONB)


class JobRow(Base):
    __tablename__ = "jobs"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    kind: Mapped[str]
    payload: Mapped[Json] = mapped_column(JSONB)
    dedupe_key: Mapped[str] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(default="queued", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    run_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    locked_at: Mapped[datetime | None]
    last_error: Mapped[str | None]


class OutboxRow(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str]
    payload: Mapped[Json] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None]
    parked: Mapped[bool] = mapped_column(default=False)
