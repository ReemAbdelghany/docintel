"""Stub parser, classifier and extractor so API tests need no Docling and no network."""

from docintel.models.errors import ProviderUnavailable
from docintel.models.parsed import Page, ParsedDocument
from docintel.models.values import Confidence, DocumentType
from docintel.shared.ports import ExtractionOutcome
from tests.unit_tests.builders import REQUIRED_EVIDENCE, a_provenance, an_invoice


class StubParser:
    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        return ParsedDocument((Page(1, "Acme Supplies\nINV-001\n2026-01-15\nTotal 1150.00"),))


class CorruptParser:
    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        from docintel.models.errors import CorruptDocument

        raise CorruptDocument("cannot read")


class StubClassifier:
    async def classify(self, doc: ParsedDocument) -> tuple[DocumentType, Confidence]:
        return DocumentType.INVOICE, Confidence(0.95)


class FlakyExtractor:
    """Fails with a transient error a set number of times, then succeeds."""

    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times, self.calls = fail_times, 0

    async def extract(self, doc: ParsedDocument) -> ExtractionOutcome:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderUnavailable("simulated outage")
        return ExtractionOutcome(an_invoice(), REQUIRED_EVIDENCE, a_provenance())
