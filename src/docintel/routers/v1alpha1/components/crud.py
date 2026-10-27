"""Database access for cases and documents."""

from uuid import UUID

from sqlalchemy import select, update
from sqlmodel import col

from docintel.models.document import Case, Document, utcnow
from docintel.shared.document_types import DocumentStatus
from docintel.utils.providers.pg_database_provider import get_async_session


async def create_case() -> Case:
    case = Case()
    async with get_async_session()() as session:
        session.add(case)
        await session.commit()
    return case


async def get_case(case_id: UUID) -> Case | None:
    async with get_async_session()() as session:
        case: Case | None = await session.get(Case, case_id)
        return case


async def add_document(
    case_id: UUID, filename: str, content_hash: str, storage_uri: str
) -> tuple[Document, bool]:
    """Insert a document, or return the existing one when the same bytes were uploaded before."""
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
    async with get_async_session()() as session:
        document: Document | None = await session.get(Document, document_id)
        return document


async def list_documents(case_id: UUID) -> list[Document]:
    async with get_async_session()() as session:
        rows = await session.execute(
            select(Document)
            .where(col(Document.case_id) == case_id)
            .order_by(col(Document.created_at))
        )
        return list(rows.scalars())


async def mark_processing(document_id: UUID) -> None:
    await save_result(document_id, status=DocumentStatus.PROCESSING, reason=None)


async def save_result(document_id: UUID, **values: object) -> None:
    async with get_async_session()() as session:
        await session.execute(
            update(Document)
            .where(col(Document.id) == document_id)
            .values(**values, updated_at=utcnow())
        )
        await session.commit()


async def interrupt_unfinished() -> int:
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
