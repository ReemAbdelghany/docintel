"""The accept / reject / review decision, with the model calls replaced by stubs."""

from datetime import date
from decimal import Decimal

from docintel.routers.v1alpha1.components.document_processor import analyze
from docintel.routers.v1alpha1.components.rules import locate_evidence
from docintel.routers.v1alpha1.schemas.document import (
    Classification,
    ContractFacts,
    FieldEvidence,
    InvoiceFacts,
)
from docintel.shared.document_types import DocumentStatus, DocumentType, ParsedPage
from docintel.shared.errors import ProviderUnavailable

PAGES = [
    ParsedPage(1, "Acme Supplies\nInvoice INV-001 dated 2026-01-15\nSubtotal 1000\nTotal 1150")
]
CONTRACT_PAGES = [ParsedPage(1, "Agreement between Acme Ltd and Nile Co, effective 2026-01-01")]


def invoice(total: str = "1150", quotes: bool = True) -> InvoiceFacts:
    quote = {"vendor_name": "Acme Supplies", "invoice_number": "INV-001", "total": "Total 1150"}
    return InvoiceFacts(
        vendor_name="Acme Supplies",
        invoice_number="INV-001",
        issue_date=date(2026, 1, 15),
        currency="EGP",
        subtotal=Decimal("1000"),
        tax=Decimal("150"),
        total=Decimal(total),
        evidence=[FieldEvidence(field=f, quote=q) for f, q in quote.items()]
        + [FieldEvidence(field="issue_date", quote="dated 2026-01-15")]
        if quotes
        else [],
    )


def classify_as(kind: DocumentType, confidence: float = 0.95):  # type: ignore[no-untyped-def]
    async def classify(pages: list[ParsedPage]) -> Classification:
        return Classification(document_type=kind, confidence=confidence)

    return classify


def extract_returning(facts: InvoiceFacts | ContractFacts):  # type: ignore[no-untyped-def]
    async def extract(kind: DocumentType, pages: list[ParsedPage]) -> InvoiceFacts | ContractFacts:
        return facts

    return extract


async def run(classify, extract, pages=PAGES):  # type: ignore[no-untyped-def]
    return await analyze(pages, classify, extract, min_confidence=0.7)


async def test_a_consistent_invoice_is_accepted() -> None:
    outcome = await run(classify_as(DocumentType.INVOICE), extract_returning(invoice()))

    assert outcome.status is DocumentStatus.ACCEPTED
    assert {e.page for e in outcome.evidence} == {1}


async def test_a_wrong_total_is_rejected() -> None:
    outcome = await run(classify_as(DocumentType.INVOICE), extract_returning(invoice("1200")))

    assert outcome.status is DocumentStatus.REJECTED
    assert outcome.findings[0].code == "TOTAL_MISMATCH"


async def test_a_document_that_is_neither_invoice_nor_contract_is_rejected() -> None:
    outcome = await run(classify_as(DocumentType.OTHER), extract_returning(invoice()))

    assert outcome.status is DocumentStatus.REJECTED


async def test_low_classification_confidence_goes_to_review() -> None:
    outcome = await run(classify_as(DocumentType.INVOICE, 0.4), extract_returning(invoice()))

    assert outcome.status is DocumentStatus.NEEDS_REVIEW


async def test_a_failed_classification_goes_to_review() -> None:
    async def broken(pages: list[ParsedPage]) -> Classification:
        raise ProviderUnavailable("down")

    outcome = await run(broken, extract_returning(invoice()))

    assert outcome.status is DocumentStatus.NEEDS_REVIEW
    assert "classification failed" in (outcome.reason or "")


async def test_a_failed_extraction_goes_to_review() -> None:
    async def broken(kind: DocumentType, pages: list[ParsedPage]) -> InvoiceFacts:
        raise ProviderUnavailable("down")

    outcome = await run(classify_as(DocumentType.INVOICE), broken)

    assert outcome.status is DocumentStatus.NEEDS_REVIEW


async def test_a_quote_that_is_not_in_the_document_goes_to_review() -> None:
    facts = invoice()
    facts.evidence[0] = FieldEvidence(field="vendor_name", quote="Globex Corporation")

    outcome = await run(classify_as(DocumentType.INVOICE), extract_returning(facts))

    assert outcome.status is DocumentStatus.NEEDS_REVIEW
    assert outcome.findings[0].code == "UNGROUNDED_EVIDENCE"


async def test_a_required_fact_without_evidence_goes_to_review() -> None:
    outcome = await run(classify_as(DocumentType.INVOICE), extract_returning(invoice(quotes=False)))

    assert outcome.status is DocumentStatus.NEEDS_REVIEW


async def test_a_contract_with_two_parties_and_a_date_is_accepted() -> None:
    facts = ContractFacts(
        parties=["Acme Ltd", "Nile Co"],
        effective_date=date(2026, 1, 1),
        evidence=[
            FieldEvidence(field="parties", quote="between Acme Ltd and Nile Co"),
            FieldEvidence(field="effective_date", quote="effective 2026-01-01"),
        ],
    )

    outcome = await run(
        classify_as(DocumentType.CONTRACT), extract_returning(facts), CONTRACT_PAGES
    )

    assert outcome.status is DocumentStatus.ACCEPTED


async def test_a_contract_ending_before_it_starts_is_rejected() -> None:
    facts = ContractFacts(
        parties=["Acme Ltd", "Nile Co"],
        effective_date=date(2026, 1, 1),
        end_date=date(2025, 1, 1),
        evidence=[
            FieldEvidence(field="parties", quote="between Acme Ltd and Nile Co"),
            FieldEvidence(field="effective_date", quote="effective 2026-01-01"),
        ],
    )

    outcome = await run(
        classify_as(DocumentType.CONTRACT), extract_returning(facts), CONTRACT_PAGES
    )

    assert outcome.status is DocumentStatus.REJECTED


def test_grounding_ignores_case_and_whitespace_and_reports_the_page() -> None:
    pages = [ParsedPage(1, "nothing"), ParsedPage(2, "Total   1150\nEGP")]

    located, findings = locate_evidence(
        [FieldEvidence(field="total", quote="TOTAL 1150 egp")], pages
    )

    assert findings == []
    assert located[0].page == 2
