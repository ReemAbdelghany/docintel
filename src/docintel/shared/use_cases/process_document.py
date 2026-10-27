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
from docintel.models.rules import ExtractionRules, ReviewPolicy
from docintel.models.services import GroundingVerifier
from docintel.models.states import DocumentStatus
from docintel.models.values import Confidence, DocumentType
from docintel.shared.ports import (
    BlobStore,
    Classifier,
    DocumentParser,
    Extractor,
    Telemetry,
    UnitOfWork,
)
from docintel.shared.registry import default_rules
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
    """Classify, extract, then verify and decide. Triggered by DocumentParsed.

    Business rules and the review policy decide the outcome. An extraction the
    rules or the grounding check doubt goes to review with readable reasons;
    nothing is accepted on the model's word alone.
    """

    def __init__(
        self,
        uow_factory: UowFactory,
        blobs: BlobStore,
        classifier: Classifier,
        extractors: Mapping[DocumentType, Extractor],
        telemetry: Telemetry,
        *,
        rules: Mapping[DocumentType, ExtractionRules] | None = None,
        policy: ReviewPolicy | None = None,
        grounding: GroundingVerifier | None = None,
        min_classification: float = 0.7,
    ) -> None:
        self._uow, self._blobs, self._classifier = uow_factory, blobs, classifier
        self._extractors, self._t = extractors, telemetry
        self._rules = rules if rules is not None else default_rules()
        self._policy = policy or ReviewPolicy(Confidence(min_classification))
        self._grounding = grounding or GroundingVerifier()

    async def __call__(self, document_id: UUID) -> None:
        parsed = await self._load_parsed(document_id)
        if parsed is None:
            return
        await self._classify(document_id, parsed)
        await self._extract(document_id, parsed)
        await self._verify_and_decide(document_id, parsed)

    async def _load_parsed(self, document_id: UUID) -> ParsedDocument | None:
        async with self._uow() as uow:
            analysis = await uow.analyses.get(document_id)
            if analysis.status not in _RESUMABLE or analysis.parsed_uri is None:
                return None  # decided, failed or not parsed yet: nothing for this job
            uri = analysis.parsed_uri
        return deserialize(await self._blobs.get(uri))

    async def _classify(self, document_id: UUID, parsed: ParsedDocument) -> None:
        async with self._uow() as uow:
            analysis = await uow.analyses.get(document_id)
            if analysis.status is not DocumentStatus.PARSED:
                return  # resumed job: already classified
        with self._t.stage("classify", document_id=str(document_id)):
            doc_type, confidence = await self._classifier.classify(parsed)  # no transaction open
        async with self._uow() as uow:
            analysis = await uow.analyses.get(document_id)
            if analysis.status is DocumentStatus.PARSED:
                analysis.classify(doc_type, confidence)
                await uow.commit()

    async def _extract(self, document_id: UUID, parsed: ParsedDocument) -> None:
        async with self._uow() as uow:
            analysis = await uow.analyses.get(document_id)
            if analysis.status is not DocumentStatus.CLASSIFIED or analysis.document_type is None:
                return  # resumed job: already past this stage
            doc_type = analysis.document_type
            extractor = self._extractors.get(doc_type)
            if extractor is None or doc_type not in self._rules:
                analysis.request_review(["UNSUPPORTED_DOCUMENT_TYPE"])
                self._t.outcome(doc_type.value, analysis.status.value)
                await uow.commit()
                return
        with self._t.stage("extract", document_id=str(document_id), doc_type=doc_type.value):
            outcome = await extractor.extract(parsed)  # slow call, no transaction open
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

    async def _verify_and_decide(self, document_id: UUID, parsed: ParsedDocument) -> None:
        async with self._uow() as uow:  # no slow calls here, one transaction is fine
            analysis = await uow.analyses.get(document_id)
            if analysis.status is not DocumentStatus.EXTRACTED or analysis.document_type is None:
                return
            current = analysis.current
            rules = self._rules[analysis.document_type]
            findings = [
                *rules.check(current.facts),
                *self._grounding.verify(current.facts, current.evidence, parsed),
            ]
            analysis.record_verification(findings)
            confidence = analysis.classification_confidence or Confidence(0.0)
            decision = self._policy.decide(findings, confidence)
            if decision.accept:
                analysis.accept()
            else:
                analysis.request_review(list(decision.reasons))
            self._t.outcome(analysis.document_type.value, analysis.status.value)
            await uow.commit()


_RESUMABLE = (DocumentStatus.PARSED, DocumentStatus.CLASSIFIED, DocumentStatus.EXTRACTED)
