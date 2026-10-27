"""Read side: SQL straight to views. Not CQRS with a second store, just no aggregate loading."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from docintel.models.errors import NotFound
from docintel.shared.queries import (
    DocumentResultView,
    DocumentStatusView,
    EvidenceView,
    FindingView,
)
from docintel.utils.providers.db.tables import AnalysisRow, ExtractionRow


class SqlQueries:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def document_status(self, document_id: UUID) -> DocumentStatusView:
        async with self._sessions() as s:
            row = await s.get(AnalysisRow, document_id)
            if row is None:
                raise NotFound(f"document {document_id}")
            return DocumentStatusView(
                document_id=row.document_id,
                case_id=row.case_id,
                filename=row.filename,
                status=row.status,
                document_type=row.document_type,
                classification_confidence=row.classification_confidence,
                findings=tuple(
                    FindingView(
                        str(f["code"]),
                        str(f["severity"]),
                        None if f.get("field") is None else str(f["field"]),
                        str(f.get("message", "")),
                    )
                    for f in row.findings
                ),
            )

    async def document_result(self, document_id: UUID) -> DocumentResultView:
        async with self._sessions() as s:
            row = await s.get(AnalysisRow, document_id)
            if row is None:
                raise NotFound(f"document {document_id}")
            extraction = (
                (
                    await s.execute(
                        select(ExtractionRow)
                        .where(ExtractionRow.document_id == document_id)
                        .order_by(ExtractionRow.version.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
            if extraction is None:
                raise NotFound(f"no result yet for document {document_id}")
            return DocumentResultView(
                document_id=document_id,
                status=row.status,
                document_type=row.document_type,
                version=extraction.version,
                facts=extraction.facts,
                evidence=tuple(
                    EvidenceView(str(e["field"]), int(str(e["page"])), str(e["snippet"]))
                    for e in extraction.evidence
                ),
                model=str(extraction.provenance["model"]),
                prompt_version=str(extraction.provenance["prompt_version"]),
                schema_version=str(extraction.provenance["schema_version"]),
            )
