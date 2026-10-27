"""Database access layer for cases and documents.

This module provides CRUD operations for the document intelligence service's
two main entities: Cases (onboarding applications) and Documents (uploaded files
with processing results). All functions use the async SQLAlchemy session from
the pg_database_provider.

Operations are designed to be idempotent where appropriate (e.g., document
deduplication by content hash) and use explicit transactions.
"""

from uuid import UUID

from sqlalchemy import select, update
from sqlmodel import col

from docintel.models.document import Case, Document, utcnow
from docintel.shared.document_types import DocumentStatus
from docintel.utils.providers.pg_database_provider import get_async_session


async def create_case() -> Case:
    """Create a new onboarding case.

    Inserts a new Case row with a generated UUID and current timestamp.
    The case serves as a container for documents from a single SME application.

    Returns:
        Case: The newly created case with id and created_at populated.
    """
    case = Case()
    async with get_async_session()() as session:
        session.add(case)
        await session.commit()
    return case


async def get_case(case_id: UUID) -> Case | None:
    """Fetch a case by ID.

    Args:
        case_id: UUID of the case to retrieve.

    Returns:
        Case | None: The case if found, None otherwise.
    """
    async with get_async_session()() as session:
        case: Case | None = await session.get(Case, case_id)
        return case


async def add_document(
    case_id: UUID, filename: str, content_hash: str, storage_uri: str
) -> tuple[Document, bool]:
    """Insert a document, or return the existing one for duplicate content.

    Implements content-addressed deduplication: if a document with the same
    content_hash already exists in the case, returns the existing document
    instead of creating a duplicate. This prevents re-processing identical files.

    Args:
        case_id: UUID of the case this document belongs to.
        filename: Original filename (for display).
        content_hash: SHA-256 hex digest of the file content.
        storage_uri: URI where the raw file is stored (local:// or s3://).

    Returns:
        tuple[Document, bool]: The document and a flag indicating whether it
            was newly created (True) or already existed (False).
    """
    async with get_async_session()() as session:
        existing = (
            await session.execute(
                select(Document).where(
                    col(Document.case_id) == case_id, col(Document.content_hash) == content_hash
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False
        document = Document(
            case_id=case_id, filename=filename, content_hash=content_hash, storage_uri=storage_uri
        )
        session.add(document)
        await session.commit()
        return document, True


async def get_document(document_id: UUID) -> Document | None:
    """Fetch a document by ID.

    Args:
        document_id: UUID of the document to retrieve.

    Returns:
        Document | None: The document if found, None otherwise.
    """
    async with get_async_session()() as session:
        document: Document | None = await session.get(Document, document_id)
        return document


async def list_documents(case_id: UUID) -> list[Document]:
    """List all documents for a case, ordered by creation time.

    Args:
        case_id: UUID of the case.

    Returns:
        list[Document]: All documents in the case, oldest first.
    """
    async with get_async_session()() as session:
        rows = await session.execute(
            select(Document)
            .where(col(Document.case_id) == case_id)
            .order_by(col(Document.created_at))
        )
        return list(rows.scalars())


async def mark_processing(document_id: UUID) -> None:
    """Reset a document to PROCESSING state and clear all previous results.

    Used when reprocessing a document. Clears all extraction results (facts,
    evidence, findings, document_type, confidence, reason, model) so that
    the new pipeline run starts fresh and old results are never shown as current.

    Args:
        document_id: UUID of the document to reset.
    """
    """Back to processing, and forget the previous result so it is never shown as current."""
    await save_result(
        document_id,
        status=DocumentStatus.PROCESSING,
        reason=None,
        document_type=None,
        classification_confidence=None,
        findings=[],
        facts=None,
        evidence=[],
        model=None,
    )


async def save_result(document_id: UUID, **values: object) -> None:
    """Update a document with processing results.

    Generic update function for writing pipeline outcomes (status, facts,
    evidence, findings, etc.) to the document record. Automatically sets
    updated_at to the current UTC timestamp.

    Args:
        document_id: UUID of the document to update.
        **values: Column names and values to update (e.g., status, facts, evidence).
    """
    async with get_async_session()() as session:
        await session.execute(
            update(Document)
            .where(col(Document.id) == document_id)
            .values(**values, updated_at=utcnow())
        )
        await session.commit()


async def interrupt_unfinished() -> int:
    """Flag documents stuck in PROCESSING after a service restart.

    On startup, any documents still marked as PROCESSING have lost their
    background task. This function finds them and marks them as NEEDS_REVIEW
    with a reason explaining the interruption, so they can be manually
    reprocessed.

    Returns:
        int: Number of documents flagged for review.
    """
    """After a restart, documents still processing lost their background task: flag them."""
    async with get_async_session()() as session:
        rows = await session.execute(
            select(col(Document.id)).where(col(Document.status) == DocumentStatus.PROCESSING)
        )
        ids = list(rows.scalars())
        for document_id in ids:
            await save_result(
                document_id,
                status=DocumentStatus.NEEDS_REVIEW,
                reason="processing was interrupted by a restart, reprocess the document",
            )
        return len(ids)
