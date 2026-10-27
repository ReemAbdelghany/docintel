"""Deterministic checks on what the model extracted. Nothing here calls a model."""

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from docintel.routers.v1alpha1.schemas.document import (
    ContractFacts,
    FieldEvidence,
    Finding,
    InvoiceFacts,
)
from docintel.shared.document_types import ParsedPage

TOLERANCE = Decimal("0.01")
STEP_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}
CURRENCY_CODES = ("EGP", "USD", "EUR", "GBP", "SAR", "AED", "KWD", "QAR")
MAX_SNIPPET = 200

Facts = InvoiceFacts | ContractFacts


def _squash(text: str) -> str:
    """Lowercase letters and digits only, so dashes, quotes, spacing and markup never matter."""
    return re.sub(r"[\W_]+", "", text.lower())


def _candidates(value: object) -> list[str]:
    """Ways a fact's value may be written in a document, squashed for comparison."""
    if isinstance(value, date):
        month_long, month_short = value.strftime("%B"), value.strftime("%b")
        forms = [
            f"{month_long} {value.day}, {value.year}",
            f"{month_short} {value.day}, {value.year}",
            f"{value.day} {month_long} {value.year}",
            f"{value.day} {month_short} {value.year}",
            value.isoformat(),
            f"{value.day:02}/{value.month:02}/{value.year}",
            f"{value.day}/{value.month}/{value.year}",
        ]
    elif isinstance(value, Decimal):
        forms = [f"{value:,.2f}", f"{value.normalize():f}", f"{int(value):,}"]
        forms += [f"{value:f}"] if value == value.to_integral() else []
    elif isinstance(value, list):
        return [c for item in value for c in _candidates(item)]
    else:
        forms = [str(value)]
    return [s for s in (_squash(f) for f in forms) if s]


def _find_in_pages(candidates: list[str], pages: list[ParsedPage]) -> tuple[int, str] | None:
    """The first line (and its page) that contains any candidate."""
    for page in pages:
        for line in page.text.splitlines():
            squashed = _squash(line)
            if any(c in squashed for c in candidates):
                return page.number, line.strip()[:MAX_SNIPPET]
    return None


def locate_evidence(
    evidence: list[FieldEvidence], pages: list[ParsedPage]
) -> tuple[list[FieldEvidence], list[Finding]]:
    """Grounding: keep quotes that really appear in the document, and record their page."""
    located: list[FieldEvidence] = []
    findings: list[Finding] = []
    for item in evidence:
        quote = _squash(item.quote)
        page = next((p.number for p in pages if quote and quote in _squash(p.text)), None)
        if page is None:
            findings.append(
                Finding(
                    code="UNGROUNDED_EVIDENCE",
                    field=item.field,
                    message=f"the quote for {item.field} was not found in the document",
                )
            )
        else:
            located.append(item.model_copy(update={"page": page}))
    return located, findings


def ground_by_value(
    facts: Facts,
    evidence: list[FieldEvidence],
    findings: list[Finding],
    pages: list[ParsedPage],
) -> tuple[list[FieldEvidence], list[Finding]]:
    """The model's quote may be sloppy while its value is right. If the value itself appears in
    the document (in any common format), use that line as the evidence instead."""
    have = {e.field for e in evidence}
    wanted = {f.field for f in findings if f.field} | set(facts.REQUIRED)
    evidence = list(evidence)
    repaired: set[str] = set()
    for name in sorted(wanted - have):
        value = getattr(facts, name, None)
        if value is None or value == []:
            continue
        found = _find_in_pages(_candidates(value), pages)
        if found is not None:
            evidence.append(FieldEvidence(field=name, quote=found[1], page=found[0]))
            repaired.add(name)
    return evidence, [f for f in findings if f.field not in repaired]


def missing_facts(facts: Facts, evidence: list[FieldEvidence]) -> list[Finding]:
    """Required facts must be present and supported by a grounded quote."""
    supported = {e.field for e in evidence}
    findings: list[Finding] = []
    for name in facts.REQUIRED:
        value = getattr(facts, name)
        if value is None or value == [] or (name == "parties" and len(value) < 2):
            message = "at least two parties are required" if name == "parties" else name
            findings.append(Finding(code="MISSING_FACT", field=name, message=f"missing: {message}"))
        elif name not in supported:
            findings.append(
                Finding(
                    code="MISSING_EVIDENCE",
                    field=name,
                    message=f"no grounded quote supports {name}",
                )
            )
    return findings


def _months_between(start: date, end: date) -> int:
    """Whole months from start to end, inclusive (1 Nov 2026 to 31 Oct 2029 is 36)."""
    return (end.year - start.year) * 12 + end.month - start.month + 1


def derive_contract_values(facts: ContractFacts, pages: list[ParsedPage]) -> list[Finding]:
    """Fill what the model left empty from the document itself, and say how it was derived.

    The currency comes from the one ISO code the text uses. The total value of a recurring
    contract is the sum of its payments, applying the yearly increase compounded.
    """
    notes: list[Finding] = []
    if facts.currency is None:
        text = " ".join(p.text for p in pages).upper()
        used = {c for c in CURRENCY_CODES if re.search(rf"\b{c}\b", text)}
        if len(used) == 1:
            facts.currency = used.pop()
            notes.append(
                Finding(
                    code="CURRENCY_INFERRED",
                    field="currency",
                    message=f"{facts.currency} is the only currency used in the document",
                )
            )
    amount, period = facts.recurring_amount, facts.recurring_period
    if amount is not None and facts.total_value == amount:
        facts.total_value = None  # the model put the periodic amount here
    if facts.total_value is not None or amount is None or period is None:
        return notes
    if facts.effective_date is None or facts.end_date is None:
        return notes
    step = STEP_MONTHS[period]
    months = _months_between(facts.effective_date, facts.end_date)
    increase = (facts.annual_increase_percent or Decimal(0)) / 100
    total = Decimal(0)
    for index in range(months // step):
        year = (index * step) // 12
        total += amount * (1 + increase) ** year
    facts.total_value = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rise = f", rising {facts.annual_increase_percent}% a year" if increase else ""
    notes.append(
        Finding(
            code="DERIVED_TOTAL_VALUE",
            field="total_value",
            message=f"{months // step} {period} payments of {amount}{rise}",
        )
    )
    return notes


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
