"""Test builders: create domain objects at any point of their life."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from docintel.models.analysis import DocumentAnalysis, Finding, Provenance
from docintel.models.facts import InvoiceFacts
from docintel.models.values import Confidence, DocumentType, Evidence, Money

REQUIRED_EVIDENCE = (
    Evidence("vendor_name", 1, "Acme Supplies"),
    Evidence("invoice_number", 1, "INV-001"),
    Evidence("issue_date", 1, "2026-01-15"),
    Evidence("total", 1, "Total 1150.00"),
)


def money(amount: str, currency: str = "EGP") -> Money:
    return Money(Decimal(amount), currency)


def an_invoice(total: str = "1150.00") -> InvoiceFacts:
    return InvoiceFacts(
        vendor_name="Acme Supplies",
        invoice_number="INV-001",
        issue_date=date(2026, 1, 15),
        subtotal=money("1000.00"),
        tax=money("150.00"),
        total=money(total),
    )


def a_provenance() -> Provenance:
    return Provenance("test-model", "invoice-v1", "invoice-facts-1", 100, 20)


def a_new_analysis() -> DocumentAnalysis:
    return DocumentAnalysis(uuid4(), uuid4(), "invoice.pdf", "local://cases/c1/invoice.pdf")


def an_extracted_analysis(
    evidence: tuple[Evidence, ...] = REQUIRED_EVIDENCE,
) -> DocumentAnalysis:
    analysis = a_new_analysis()
    analysis.record_parse()
    analysis.classify(DocumentType.INVOICE, Confidence(0.95))
    analysis.record_extraction(an_invoice(), evidence, a_provenance())
    return analysis


def a_validated_analysis(
    findings: list[Finding] | None = None,
    evidence: tuple[Evidence, ...] = REQUIRED_EVIDENCE,
) -> DocumentAnalysis:
    analysis = an_extracted_analysis(evidence)
    analysis.record_verification(findings or [])
    return analysis


def an_accepted_analysis() -> DocumentAnalysis:
    analysis = a_validated_analysis()
    analysis.accept()
    return analysis
