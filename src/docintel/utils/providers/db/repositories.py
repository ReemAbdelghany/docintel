"""Data-mapper repositories: rows in, aggregates out. The domain never becomes an ORM entity."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docintel.models.analysis import DocumentAnalysis
from docintel.models.errors import NotFound
from docintel.models.onboarding_case import OnboardingCase, SubmittedDocument
from docintel.utils.providers.db.mappers import (
    apply_to_row,
    extraction_to_row,
    to_domain,
    to_row,
)
from docintel.utils.providers.db.tables import (
    AnalysisRow,
    CaseRow,
    ExtractionRow,
    SubmittedDocumentRow,
)


class SqlAnalysisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self.seen: dict[UUID, DocumentAnalysis] = {}
        self._persisted_versions: dict[UUID, int] = {}
        self._new: set[UUID] = set()

    async def get(self, document_id: UUID) -> DocumentAnalysis:
        row = await self._s.get(AnalysisRow, document_id)
        if row is None:
            raise NotFound(f"document {document_id}")
        extractions = list(
            (
                await self._s.execute(
                    select(ExtractionRow)
                    .where(ExtractionRow.document_id == document_id)
                    .order_by(ExtractionRow.version)
                )
            )
            .scalars()
            .all()
        )
        analysis = to_domain(row, extractions)
        self.seen[document_id] = analysis
        self._persisted_versions[document_id] = len(extractions)
        return analysis

    async def exists(self, document_id: UUID) -> bool:
        return await self._s.get(AnalysisRow, document_id) is not None

    def add(self, analysis: DocumentAnalysis) -> None:
        self.seen[analysis.document_id] = analysis
        self._new.add(analysis.document_id)
        self._persisted_versions[analysis.document_id] = 0

    async def flush_changes(self) -> None:
        for document_id, analysis in self.seen.items():
            if document_id in self._new:
                self._s.add(to_row(analysis))
                await self._s.flush()  # the row must exist before its extractions
            else:
                row = await self._s.get(AnalysisRow, document_id)
                if row is None:
                    raise NotFound(f"document {document_id}")
                apply_to_row(analysis, row)
            for extraction in analysis.extractions[self._persisted_versions[document_id] :]:
                self._s.add(extraction_to_row(document_id, extraction))
        self._new.clear()


class SqlCaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self.seen: dict[UUID, OnboardingCase] = {}
        self._persisted: dict[UUID, set[str]] = {}
        self._new: set[UUID] = set()

    async def get(self, case_id: UUID) -> OnboardingCase:
        row = await self._s.get(CaseRow, case_id)
        if row is None:
            raise NotFound(f"case {case_id}")
        docs = (
            (
                await self._s.execute(
                    select(SubmittedDocumentRow).where(SubmittedDocumentRow.case_id == case_id)
                )
            )
            .scalars()
            .all()
        )
        case = OnboardingCase(case_id)
        case.closed = row.closed
        for d in docs:
            case.restore(SubmittedDocument(d.id, d.filename, d.content_hash, d.storage_uri))
        self.seen[case_id] = case
        self._persisted[case_id] = {d.content_hash for d in docs}
        return case

    def add(self, case: OnboardingCase) -> None:
        self.seen[case.case_id] = case
        self._new.add(case.case_id)
        self._persisted[case.case_id] = set()

    async def flush_changes(self) -> None:
        for case_id, case in self.seen.items():
            if case_id in self._new:
                self._s.add(CaseRow(case_id=case_id, closed=case.closed))
                await self._s.flush()
            else:
                row = await self._s.get(CaseRow, case_id)
                if row is not None:
                    row.closed = case.closed
            for doc in case.documents:
                if doc.content_hash not in self._persisted[case_id]:
                    self._s.add(
                        SubmittedDocumentRow(
                            id=doc.id,
                            case_id=case_id,
                            content_hash=doc.content_hash,
                            filename=doc.filename,
                            storage_uri=doc.storage_uri,
                        )
                    )
        self._new.clear()
