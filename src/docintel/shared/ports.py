"""Ports: the Protocols every use case depends on. Adapters live in utils/providers/."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Self
from uuid import UUID

from docintel.models.analysis import DocumentAnalysis, Provenance
from docintel.models.facts import Facts
from docintel.models.onboarding_case import OnboardingCase
from docintel.models.parsed import ParsedDocument
from docintel.models.values import Confidence, DocumentType, Evidence


class DocumentParser(Protocol):
    async def parse(self, content: bytes, filename: str) -> ParsedDocument: ...


class Classifier(Protocol):
    async def classify(self, doc: ParsedDocument) -> tuple[DocumentType, Confidence]: ...


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    facts: Facts
    evidence: tuple[Evidence, ...]
    provenance: Provenance


class Extractor(Protocol):
    async def extract(self, doc: ParsedDocument) -> ExtractionOutcome: ...


class BlobStore(Protocol):
    async def put(self, key: str, data: bytes) -> str:
        """Store bytes and return a URI that identifies where they live."""
        ...

    async def get(self, uri: str) -> bytes: ...


class JobQueue(Protocol):
    async def enqueue(
        self,
        kind: str,
        payload: dict[str, str],
        dedupe_key: str,
        run_at: datetime | None = None,
    ) -> None: ...


class AnalysisRepository(Protocol):
    async def get(self, document_id: UUID) -> DocumentAnalysis: ...
    async def exists(self, document_id: UUID) -> bool: ...
    def add(self, analysis: DocumentAnalysis) -> None: ...


class CaseRepository(Protocol):
    async def get(self, case_id: UUID) -> OnboardingCase: ...
    def add(self, case: OnboardingCase) -> None: ...


class UnitOfWork(Protocol):
    """One transaction. Aggregate state, queued jobs and outbox events commit together."""

    analyses: AnalysisRepository
    cases: CaseRepository
    jobs: JobQueue

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc: object) -> None: ...
    async def commit(self) -> None: ...


class Telemetry(Protocol):
    def stage(self, name: str, **attrs: str) -> AbstractContextManager[None]: ...
    def llm_usage(self, model: str, input_tokens: int, output_tokens: int) -> None: ...
    def outcome(self, doc_type: str, status: str) -> None: ...
