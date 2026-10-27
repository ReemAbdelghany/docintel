"""Unit tests for the accept/reject/review decision logic.

This module tests the complete document processing pipeline decision logic
with LLM calls replaced by stubs. It verifies the final document status
(accepted/rejected/needs_review) under various scenarios:

- Invoice validation (totals, line items, evidence grounding)
- Contract validation (dates, parties, business rules)
- Classification confidence thresholds
- Provider failure handling
- Evidence grounding and repair

Test helpers:
- PAGES: Sample invoice document text
- CONTRACT_PAGES: Sample contract document text
- invoice(): Factory for InvoiceFacts with configurable total and quotes
- classify_as(): Stub classifier returning specified type/confidence
- extract_returning(): Stub extractor returning specified facts
- run(): Execute full pipeline with stubbed classify/extract
"""

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

# Sample invoice document text
PAGES = [
    ParsedPage(1, "Acme Supplies\nInvoice INV-001 dated 2026-01-15\nSubtotal 1000\nTotal 1150")
]
# Sample contract document text
CONTRACT_PAGES = [ParsedPage(1, "Agreement between Acme Ltd and Nile Co, effective 2026-01-01")]


def invoice(total: str = "1150", quotes: bool = True) -> InvoiceFacts:
    """Create InvoiceFacts for the sample invoice with optional total and quotes.

    Args:
        total: Total amount as string (default "1150" matching the document).
        quotes: Whether to include model-provided evidence quotes.

    Returns:
        InvoiceFacts: Invoice facts with vendor, number, date, amounts, and evidence.
    """
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
    """Create a stub classifier that returns the specified type and confidence.

    Args:
        kind: DocumentType to return.
        confidence: Confidence score to return (default 0.95).

    Returns:
        Async function matching the Classify signature.
    """

    async def classify(pages: list[ParsedPage]) -> Classification:
        return Classification(document_type=kind, confidence=confidence)

    return classify


def extract_returning(facts: InvoiceFacts | ContractFacts):  # type: ignore[no-untyped-def]
    """Create a stub extractor that returns the specified facts.

    Args:
        facts: Facts to return from extraction.

    Returns:
        Async function matching the Extract signature.
    """

    async def extract(kind: DocumentType, pages: list[ParsedPage]) -> InvoiceFacts | ContractFacts:
        return facts

    return extract


async def run(classify, extract, pages=PAGES):  # type: ignore[no-untyped-def]
    """Run the full analysis pipeline with stubbed classify/extract.

    Args:
        classify: Stub classifier function.
        extract: Stub extractor function.
        pages: Document pages to process (default: sample invoice).

    Returns:
        Outcome: Pipeline result with status, findings, evidence.
    """
    return await analyze(pages, classify, extract, min_confidence=0.7)


async def test_a_consistent_invoice_is_accepted() -> None:
    """Test that a valid invoice with matching totals and grounded evidence is accepted.

    The invoice has subtotal=1000, tax=150, total=1150 (consistent),
    all required fields present, and all quotes grounded in the document.
    """
    outcome = await run(classify_as(DocumentType.INVOICE), extract_returning(invoice()))

    assert outcome.status is DocumentStatus.ACCEPTED
    assert {e.page for e in outcome.evidence} == {1}


async def test_a_wrong_total_is_rejected() -> None:
    """Test that an invoice with inconsistent total is rejected.

    The document shows Total 1150 but the model extracts total=1200.
    The TOTAL_MISMATCH business rule should trigger REJECTED status.
    """
    outcome = await run(classify_as(DocumentType.INVOICE), extract_returning(invoice("1200")))

    assert outcome.status is DocumentStatus.REJECTED
    assert outcome.findings[0].code == "TOTAL_MISMATCH"


async def test_a_document_that_is_neither_invoice_nor_contract_is_rejected() -> None:
    """Test that OTHER document type is rejected regardless of extraction.

    Even if extraction succeeds, a document classified as OTHER (not invoice
    or contract) should be REJECTED per business rules.
    """
    outcome = await run(classify_as(DocumentType.OTHER), extract_returning(invoice()))

    assert outcome.status is DocumentStatus.REJECTED


async def test_low_classification_confidence_goes_to_review() -> None:
    """Test that classification confidence below threshold triggers NEEDS_REVIEW.

    With confidence=0.4 (below min_confidence=0.7), the document should go
    to review even if extraction would succeed.
    """
    outcome = await run(classify_as(DocumentType.INVOICE, 0.4), extract_returning(invoice()))

    assert outcome.status is DocumentStatus.NEEDS_REVIEW


async def test_a_failed_classification_goes_to_review() -> None:
    """Test that a provider failure during classification triggers NEEDS_REVIEW.

    When the classifier raises ProviderUnavailable, the pipeline should catch
    it and return NEEDS_REVIEW with a descriptive reason.
    """

    async def broken(pages: list[ParsedPage]) -> Classification:
        raise ProviderUnavailable("down")

    outcome = await run(broken, extract_returning(invoice()))

    assert outcome.status is DocumentStatus.NEEDS_REVIEW
    assert "classification failed" in (outcome.reason or "")


async def test_a_failed_extraction_goes_to_review() -> None:
    """Test that a provider failure during extraction triggers NEEDS_REVIEW.

    When the extractor raises ProviderUnavailable after successful classification,
    the pipeline should catch it and return NEEDS_REVIEW.
    """

    async def broken(kind: DocumentType, pages: list[ParsedPage]) -> InvoiceFacts:
        raise ProviderUnavailable("down")

    outcome = await run(classify_as(DocumentType.INVOICE), broken)

    assert outcome.status is DocumentStatus.NEEDS_REVIEW


async def test_a_value_that_is_not_in_the_document_goes_to_review() -> None:
    """Test that an ungrounded quote for a value not in the document triggers review.

    The model extracts vendor_name="Globex Corporation" with a matching quote,
    but neither appears in the document. The UNGROUNDED_EVIDENCE finding
    should cause NEEDS_REVIEW.
    """
    facts = invoice()
    facts.vendor_name = "Globex Corporation"  # not in the document, and neither is its quote
    facts.evidence[0] = FieldEvidence(field="vendor_name", quote="Globex Corporation")

    outcome = await run(classify_as(DocumentType.INVOICE), extract_returning(facts))

    assert outcome.status is DocumentStatus.NEEDS_REVIEW
    assert outcome.findings[0].code == "UNGROUNDED_EVIDENCE"


async def test_a_required_fact_without_a_quote_is_grounded_by_its_value() -> None:
    """Test that missing quotes are repaired when the value exists in the document.

    The model extracts all required facts but provides no quotes (quotes=False).
    The ground_by_value step should find each value in the document and
    create grounded evidence, resulting in ACCEPTED.
    """
    outcome = await run(classify_as(DocumentType.INVOICE), extract_returning(invoice(quotes=False)))

    assert outcome.status is DocumentStatus.ACCEPTED
    assert {e.field for e in outcome.evidence} >= {"vendor_name", "invoice_number", "total"}


async def test_a_required_fact_missing_from_the_document_goes_to_review() -> None:
    """Test that a required fact value not in the document triggers MISSING_EVIDENCE.

    The model extracts invoice_number="INV-999" but the document says "INV-001".
    Even with ground_by_value attempting repair, the value isn't found, so
    MISSING_EVIDENCE finding causes NEEDS_REVIEW.
    """
    facts = invoice(quotes=False)
    facts.invoice_number = "INV-999"  # the document says INV-001

    outcome = await run(classify_as(DocumentType.INVOICE), extract_returning(facts))

    assert outcome.status is DocumentStatus.NEEDS_REVIEW
    assert outcome.findings[0].code == "MISSING_EVIDENCE"


async def test_a_contract_with_two_parties_and_a_date_is_accepted() -> None:
    """Test that a valid contract with parties and effective date is accepted.

    Contract requires parties (>=2) and effective_date, both present and
    grounded in the document text.
    """
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
    """Test that a contract with end_date before effective_date is rejected.

    The DATE_ORDER business rule should trigger REJECTED when the contract
    expiration precedes its start date.
    """
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
    """Test that evidence grounding is case/whitespace insensitive and reports page.

    The quote "TOTAL 1150 egp" (different case/spacing) should match the
    document line "Total   1150\nEGP" on page 2, and the page should be
    correctly reported as 2.
    """
    pages = [ParsedPage(1, "nothing"), ParsedPage(2, "Total   1150\nEGP")]

    located, findings = locate_evidence(
        [FieldEvidence(field="total", quote="TOTAL 1150 egp")], pages
    )

    assert findings == []
    assert located[0].page == 2
