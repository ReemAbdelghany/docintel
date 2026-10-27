"""Understanding: start, parse and analyse a document.

Every use case follows one pattern, which makes any job safe to run twice:
load and return early if the stage is done; close the transaction before any
slow call; do the slow call; reload, call one aggregate method, commit.
"""

from collections.abc import Callable, Mapping
from uuid import UUID

from docintel.models.analysis import DocumentAnalysis
from docintel.models.events import DocumentSubmitted
from docintel.models.parsed import ParsedDocument
from docintel.models.states import DocumentStatus
from docintel.models.values import DocumentType
from docintel.shared.ports import (
    BlobStore,
    Classifier,
    DocumentParser,
    ExtractionOutcome,
    Extractor,
    Telemetry,
    UnitOfWork,
)
from docintel.shared.serialization import deserialize, serialize

UowFactory = Callable[[], UnitOfWork]


def parsed_key(document_id: UUID) -> str:
    return f"parsed/{document_id}.json"


class StartAnalysis:
    """Runs from the outbox relay when intake publishes DocumentSubmitted."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow = uow_factory

    async def __call__(self, event: DocumentSubmitted) -> None:
        async with self._uow() as uow:
            if await uow.analyses.exists(event.document_id):
                return  # at-least-once delivery, so be idempotent
            uow.analyses.add(
                DocumentAnalysis(
                    event.document_id, event.case_id, event.filename, event.storage_uri
                )
            )
            await uow.jobs.enqueue(
                "parse_document",
                {"document_id": str(event.document_id)},
                dedupe_key=f"parse:{event.document_id}",
            )
            await uow.commit()


class ParseDocument:
    def __init__(
        self,
        uow_factory: UowFactory,
        blobs: BlobStore,
        parser: DocumentParser,
        telemetry: Telemetry,
    ) -> None:
        self._uow, self._blobs, self._parser, self._t = uow_factory, blobs, parser, telemetry

    async def __call__(self, document_id: UUID) -> None:
        async with self._uow() as uow:
            analysis = await uow.analyses.get(document_id)
            if analysis.status is not DocumentStatus.RECEIVED:
                return  # already done
            uri, filename = analysis.storage_uri, analysis.filename
        content = await self._blobs.get(uri)
        with self._t.stage("parse", document_id=str(document_id)):
            parsed = await self._parser.parse(content, filename)
        parsed_uri = await self._blobs.put(parsed_key(document_id), serialize(parsed))
        async with self._uow() as uow:
            analysis = await uow.analyses.get(document_id)
            if analysis.status is DocumentStatus.RECEIVED:
                analysis.record_parse(parsed_uri)
                await uow.commit()


class AnalyzeDocument:
    """Classify, extract, then verify and decide. Triggered by DocumentParsed."""

    def __init__(
        self,
        uow_factory: UowFactory,
        blobs: BlobStore,
        classifier: Classifier,
        extractors: Mapping[DocumentType, Extractor],
        telemetry: Telemetry,
    ) -> None:
        self._uow, self._blobs, self._classifier = uow_factory, blobs, classifier
        self._extractors, self._t = extractors, telemetry

    async def __call__(self, document_id: UUID) -> None:
        parsed = await self._load_parsed(document_id)
        if parsed is None:
            return
        doc_type = await self._classify(document_id, parsed)
        if doc_type is None:
            return
        outcome = await self._extract(document_id, doc_type, parsed)
        if outcome is None:
            return
        await self._verify_and_decide(document_id)

    async def _load_parsed(self, document_id: UUID) -> ParsedDocument | None:
        async with self._uow() as uow:
            analysis = await uow.analyses.get(document_id)
            if analysis.status not in (DocumentStatus.PARSED, DocumentStatus.CLASSIFIED):
                return None  # nothing left to do for this stage range
            if analysis.parsed_uri is None:
                return None
            uri = analysis.parsed_uri
        return deserialize(await self._blobs.get(uri))

    async def _classify(self, document_id: UUID, parsed: ParsedDocument) -> DocumentType | None:
        async with self._uow() as uow:
            analysis = await uow.analyses.get(document_id)
            if analysis.status is DocumentStatus.CLASSIFIED and analysis.document_type:
                return analysis.document_type  # resume after a retry or a reprocess
        with self._t.stage("classify", document_id=str(document_id)):
            doc_type, confidence = await self._classifier.classify(parsed)
        async with self._uow() as uow:
            analysis = await uow.analyses.get(document_id)
            if analysis.status is DocumentStatus.PARSED:
                analysis.classify(doc_type, confidence)
                await uow.commit()
        return doc_type

    async def _extract(
        self, document_id: UUID, doc_type: DocumentType, parsed: ParsedDocument
    ) -> ExtractionOutcome | None:
        extractor = self._extractors.get(doc_type)
        async with self._uow() as uow:
            analysis = await uow.analyses.get(document_id)
            if analysis.status is not DocumentStatus.CLASSIFIED:
                return None
            if extractor is None:
                analysis.fail(f"unsupported document type: {doc_type}")
                await uow.commit()
                return None
        with self._t.stage("extract", document_id=str(document_id), doc_type=str(doc_type)):
            outcome = await extractor.extract(parsed)
        self._t.llm_usage(
            outcome.provenance.model,
            outcome.provenance.input_tokens,
            outcome.provenance.output_tokens,
        )
        async with self._uow() as uow:
            analysis = await uow.analyses.get(document_id)
            if analysis.status is DocumentStatus.CLASSIFIED:
                analysis.record_extraction(outcome.facts, outcome.evidence, outcome.provenance)
                await uow.commit()
        return outcome

    async def _verify_and_decide(self, document_id: UUID) -> None:
        """Filled in at M6 with grounding, business rules and the review policy.

        Until then every extraction is accepted so the pipeline runs end to end.
        """
        async with self._uow() as uow:
            analysis = await uow.analyses.get(document_id)
            if analysis.status is not DocumentStatus.EXTRACTED:
                return
            analysis.record_verification([])
            analysis.accept()
            await uow.commit()
