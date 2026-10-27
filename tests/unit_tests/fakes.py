"""In-memory fakes for every port, plus a harness that plays the outbox relay."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Self
from uuid import UUID, uuid4

from docintel.models.analysis import DocumentAnalysis
from docintel.models.errors import BlobNotFound, NotFound, ProviderUnavailable
from docintel.models.events import DocumentParsed, DocumentSubmitted, DomainEvent
from docintel.models.onboarding_case import OnboardingCase
from docintel.models.parsed import Page, ParsedDocument
from docintel.models.states import DocumentStatus
from docintel.models.values import Confidence, DocumentType
from docintel.shared.ports import ExtractionOutcome
from docintel.shared.use_cases.process_document import (
    AnalyzeDocument,
    ParseDocument,
    StartAnalysis,
)
from docintel.shared.use_cases.submit_document import SubmitDocument
from tests.unit_tests.builders import REQUIRED_EVIDENCE, a_provenance, an_invoice


@dataclass(frozen=True, slots=True)
class Job:
    kind: str
    payload: dict[str, str]
    dedupe_key: str


@dataclass
class Store:
    """The 'database': what survives between units of work."""

    analyses: dict[UUID, DocumentAnalysis] = field(default_factory=dict)
    cases: dict[UUID, OnboardingCase] = field(default_factory=dict)
    jobs: list[Job] = field(default_factory=list)
    events: list[DomainEvent] = field(default_factory=list)  # the outbox
    open_uows: int = 0

    def assert_no_open_transaction(self) -> None:
        assert self.open_uows == 0, "a slow call ran while a transaction was open"


class InMemoryJobQueue:
    def __init__(self, store: Store) -> None:
        self._store = store

    async def enqueue(
        self,
        kind: str,
        payload: dict[str, str],
        dedupe_key: str,
        run_at: datetime | None = None,
    ) -> None:
        if all(job.dedupe_key != dedupe_key for job in self._store.jobs):
            self._store.jobs.append(Job(kind, payload, dedupe_key))


class InMemoryAnalyses:
    def __init__(self, store: Store, touched: list[DocumentAnalysis | OnboardingCase]) -> None:
        self._store, self._touched = store, touched

    async def get(self, document_id: UUID) -> DocumentAnalysis:
        analysis = self._store.analyses.get(document_id)
        if analysis is None:
            raise NotFound(str(document_id))
        self._touched.append(analysis)
        return analysis

    async def exists(self, document_id: UUID) -> bool:
        return document_id in self._store.analyses

    def add(self, analysis: DocumentAnalysis) -> None:
        self._store.analyses[analysis.document_id] = analysis
        self._touched.append(analysis)


class InMemoryCases:
    def __init__(self, store: Store, touched: list[DocumentAnalysis | OnboardingCase]) -> None:
        self._store, self._touched = store, touched

    async def get(self, case_id: UUID) -> OnboardingCase:
        case = self._store.cases.get(case_id)
        if case is None:
            raise NotFound(str(case_id))
        self._touched.append(case)
        return case

    def add(self, case: OnboardingCase) -> None:
        self._store.cases[case.case_id] = case
        self._touched.append(case)


class InMemoryUnitOfWork:
    """Collects events from every aggregate it touched and writes them to the outbox on commit."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._touched: list[DocumentAnalysis | OnboardingCase] = []
        self.analyses = InMemoryAnalyses(store, self._touched)
        self.cases = InMemoryCases(store, self._touched)
        self.jobs = InMemoryJobQueue(store)

    async def __aenter__(self) -> Self:
        self._store.open_uows += 1
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._store.open_uows -= 1

    async def commit(self) -> None:
        for aggregate in self._touched:
            self._store.events.extend(aggregate.pull_events())
        self._touched.clear()


class InMemoryBlobStore:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> str:
        self._blobs[key] = data
        return f"memory://{key}"

    async def get(self, uri: str) -> bytes:
        try:
            return self._blobs[uri.removeprefix("memory://")]
        except KeyError:
            raise BlobNotFound(uri) from None


class FakeParser:
    def __init__(self, store: Store) -> None:
        self._store = store
        self.calls = 0

    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        self._store.assert_no_open_transaction()
        self.calls += 1
        return ParsedDocument((Page(1, "Acme Supplies\nINV-001\nTotal 1150.00"),))


class FakeClassifier:
    def __init__(self, store: Store, doc_type: DocumentType = DocumentType.INVOICE) -> None:
        self._store, self._doc_type = store, doc_type

    async def classify(self, doc: ParsedDocument) -> tuple[DocumentType, Confidence]:
        self._store.assert_no_open_transaction()
        return self._doc_type, Confidence(0.95)


class FakeExtractor:
    def __init__(self, store: Store, fail_times: int = 0) -> None:
        self._store, self._fail_times = store, fail_times
        self.calls = 0

    async def extract(self, doc: ParsedDocument) -> ExtractionOutcome:
        self._store.assert_no_open_transaction()
        self.calls += 1
        if self.calls <= self._fail_times:
            raise ProviderUnavailable("simulated outage")
        return ExtractionOutcome(an_invoice(), REQUIRED_EVIDENCE, a_provenance())


class NullTelemetry:
    def stage(self, name: str, **attrs: str):  # type: ignore[no-untyped-def]
        from contextlib import nullcontext

        return nullcontext()

    def llm_usage(self, model: str, input_tokens: int, output_tokens: int) -> None:
        pass

    def outcome(self, doc_type: str, status: str) -> None:
        pass


class Pipeline:
    """Wires the use cases to fakes and plays the part of the outbox relay and the worker."""

    def __init__(
        self,
        doc_type: DocumentType = DocumentType.INVOICE,
        extractor_failures: int = 0,
    ) -> None:
        self.store = Store()
        self.case_id = uuid4()
        self.store.cases[self.case_id] = OnboardingCase(self.case_id)
        blobs = InMemoryBlobStore()

        def uow() -> InMemoryUnitOfWork:
            return InMemoryUnitOfWork(self.store)

        telemetry = NullTelemetry()
        self.parser = FakeParser(self.store)
        self.extractor = FakeExtractor(self.store, fail_times=extractor_failures)
        self.submit_document = SubmitDocument(uow, blobs)
        self.start = StartAnalysis(uow)
        self.parse = ParseDocument(uow, blobs, self.parser, telemetry)
        self.analyze = AnalyzeDocument(
            uow,
            blobs,
            FakeClassifier(self.store, doc_type),
            {DocumentType.INVOICE: self.extractor},
            telemetry,
        )
        self._dispatched = 0
        self._jobs_run: set[str] = set()

    async def submit(self, content: bytes = b"%PDF fake", filename: str = "invoice.pdf") -> UUID:
        result = await self.submit_document(self.case_id, filename, content)
        return result.document_id

    async def run_all(self) -> None:
        """Deliver outbox events and run queued jobs until nothing is left to do."""
        progressed = True
        while progressed:
            progressed = False
            while self._dispatched < len(self.store.events):
                event = self.store.events[self._dispatched]
                self._dispatched += 1
                progressed = True
                match event:
                    case DocumentSubmitted():
                        await self.start(event)
                    case DocumentParsed():
                        await self.analyze(event.document_id)
            for job in list(self.store.jobs):
                if job.dedupe_key in self._jobs_run:
                    continue
                self._jobs_run.add(job.dedupe_key)
                progressed = True
                if job.kind == "parse_document":
                    await self.parse(UUID(job.payload["document_id"]))

    def status(self, document_id: UUID) -> DocumentStatus:
        return self.store.analyses[document_id].status

    def events_of(self, document_id: UUID) -> list[type[DomainEvent]]:
        return [type(e) for e in self.store.events if e.document_id == document_id]
