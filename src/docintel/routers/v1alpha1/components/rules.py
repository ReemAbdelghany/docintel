"""Deterministic checks on what the model extracted. Nothing here calls a model."""

from decimal import Decimal

from docintel.routers.v1alpha1.schemas.document import (
    ContractFacts,
    FieldEvidence,
    Finding,
    InvoiceFacts,
)
from docintel.shared.document_types import ParsedPage

TOLERANCE = Decimal("0.01")

Facts = InvoiceFacts | ContractFacts


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def locate_evidence(
    evidence: list[FieldEvidence], pages: list[ParsedPage]
) -> tuple[list[FieldEvidence], list[Finding]]:
    """Grounding: keep only quotes that really appear in the document, and record their page."""
    located: list[FieldEvidence] = []
    findings: list[Finding] = []
    for item in evidence:
        quote = _norm(item.quote)
        page = next((p.number for p in pages if quote and quote in _norm(p.text)), None)
        if page is None:
            findings.append(
                Finding(
                    code="UNGROUNDED_EVIDENCE",
                    message=f"the quote for {item.field} was not found in the document",
                )
            )
        else:
            located.append(item.model_copy(update={"page": page}))
    return located, findings


def missing_facts(facts: Facts, evidence: list[FieldEvidence]) -> list[Finding]:
    """Required facts must be present and supported by a grounded quote."""
    supported = {e.field for e in evidence}
    findings: list[Finding] = []
    for name in facts.REQUIRED:
        value = getattr(facts, name)
        if value is None or value == [] or (name == "parties" and len(value) < 2):
            message = "at least two parties are required" if name == "parties" else name
            findings.append(Finding(code="MISSING_FACT", message=f"missing: {message}"))
        elif name not in supported:
            findings.append(
                Finding(code="MISSING_EVIDENCE", message=f"no grounded quote supports {name}")
            )
    return findings


def business_violations(facts: Facts) -> list[Finding]:
    """Rules a readable document can still break. These reject the document."""
    findings: list[Finding] = []
    if isinstance(facts, InvoiceFacts):
        if None not in (facts.subtotal, facts.tax, facts.total):
            expected = facts.subtotal + facts.tax  # type: ignore[operator]
            if abs(expected - facts.total) > TOLERANCE:  # type: ignore[operator]
                findings.append(
                    Finding(
                        code="TOTAL_MISMATCH",
                        message=f"subtotal plus tax is {expected} but the total is {facts.total}",
                    )
                )
        if facts.line_items and facts.subtotal is not None:
            items = sum((i.amount for i in facts.line_items), Decimal(0))
            if abs(items - facts.subtotal) > TOLERANCE:
                findings.append(
                    Finding(
                        code="LINE_ITEMS_MISMATCH",
                        message=f"line items add up to {items}, the subtotal is {facts.subtotal}",
                    )
                )
    elif facts.effective_date and facts.end_date and facts.end_date < facts.effective_date:
        findings.append(Finding(code="DATE_ORDER", message="the contract ends before it starts"))
    currency = facts.currency
    if currency is not None and not (len(currency) == 3 and currency.isalpha()):
        findings.append(Finding(code="INVALID_CURRENCY", message=f"bad currency code: {currency}"))
    return findings
