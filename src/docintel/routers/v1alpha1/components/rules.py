"""Deterministic verification rules for extracted document facts.

This module implements all deterministic checks on model-extracted facts.
**No model calls are made here** - all logic is pure Python operating on the
structured output from the LLM and the parsed document text.

The verification pipeline:
1. locate_evidence: Ground model-provided quotes to actual document pages
2. ground_by_value: Repair missing/ungrounded evidence by searching for the
   extracted value itself in the document
3. missing_facts: Check that all required facts are present and grounded
4. derive_contract_values: Infer missing contract fields (currency, total_value)
5. business_violations: Check business rules that can reject a readable document

All functions are pure and testable without any external dependencies.
"""

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

# Tolerance for monetary comparisons (1 cent)
TOLERANCE = Decimal("0.01")
# Months per period for contract total calculation
STEP_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}
# Known ISO currency codes to search for in document text
CURRENCY_CODES = ("EGP", "USD", "EUR", "GBP", "SAR", "AED", "KWD", "QAR")
# Maximum characters to include in evidence snippets
MAX_SNIPPET = 200

Facts = InvoiceFacts | ContractFacts


def _squash(text: str) -> str:
    """Normalize text for fuzzy matching: lowercase alphanumeric only.

    Removes all non-alphanumeric characters (punctuation, whitespace, symbols)
    and lowercases. This allows matching quotes regardless of formatting
    differences (dashes, quotes, spacing, currency symbols, etc.).

    Args:
        text: Input text to normalize.

    Returns:
        str: Lowercase alphanumeric-only string.
    """
    return re.sub(r"[\W_]+", "", text.lower())


def _candidates(value: object) -> list[str]:
    """Generate all common textual representations of a fact value.

    Produces squashed variants of a value as it might appear in a document.
    Used for searching the parsed text when the model's quote is missing or
    ungrounded but the value itself is correct.

    Args:
        value: The extracted fact value (date, Decimal, list, or other).

    Returns:
        list[str]: Squashed candidate strings to search for.
    """
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
    """Search parsed pages for the first line containing any candidate.

    Scans pages in order, lines in order, returning the first match with its
    page number and the original line (truncated to MAX_SNIPPET).

    Args:
        candidates: Squashed strings to search for.
        pages: Parsed document pages.

    Returns:
        tuple[int, str] | None: (page_number, matching_line) or None if not found.
    """
    for page in pages:
        for line in page.text.splitlines():
            squashed = _squash(line)
            if any(c in squashed for c in candidates):
                return page.number, line.strip()[:MAX_SNIPPET]
    return None


def locate_evidence(
    evidence: list[FieldEvidence], pages: list[ParsedPage]
) -> tuple[list[FieldEvidence], list[Finding]]:
    """Ground model-provided quotes to actual document pages.

    For each evidence item, searches the parsed document for the exact quote
    (normalized via _squash). If found, records the page number. If not found,
    creates an UNGROUNDED_EVIDENCE finding.

    Args:
        evidence: List of FieldEvidence from the model (quotes without page numbers).
        pages: Parsed document pages to search.

    Returns:
        tuple: (located_evidence, findings)
            - located_evidence: Evidence items with page numbers filled in
            - findings: UNGROUNDED_EVIDENCE findings for quotes not found
    """
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
    """Repair missing evidence by searching for the extracted value itself.

    The model may extract the correct value but provide a sloppy/ungrounded quote.
    This function searches for the value (in common formats) in the document text.
    If found, adds new evidence with the correct quote and page. Removes any
    MISSING_EVIDENCE findings for repaired fields.

    Args:
        facts: Extracted facts (InvoiceFacts or ContractFacts).
        evidence: Already-grounded evidence from locate_evidence.
        findings: Findings from locate_evidence (may include MISSING_EVIDENCE).
        pages: Parsed document pages to search.

    Returns:
        tuple: (updated_evidence, updated_findings)
            - updated_evidence: Original evidence plus any repaired items
            - updated_findings: Findings with repaired fields removed
    """
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
    """Check that all required facts are present and have grounded evidence.

    For each required field (per facts.REQUIRED), verifies:
    1. The fact value is not None/empty (special case: parties needs >= 2)
    2. There is grounded evidence supporting the fact

    Args:
        facts: Extracted facts with REQUIRED class variable.
        evidence: Grounded evidence items.

    Returns:
        list[Finding]: MISSING_FACT or MISSING_EVIDENCE findings for each gap.
    """
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
    """Calculate whole months between two dates, inclusive.

    Used for contract total value calculation. Counts the number of period
    starts between effective_date and end_date inclusive.

    Example: 1 Nov 2026 to 31 Oct 2029 = 36 months (3 years * 12)

    Args:
        start: Start date (inclusive).
        end: End date (inclusive).

    Returns:
        int: Number of whole months.
    """
    return (end.year - start.year) * 12 + end.month - start.month + 1


def derive_contract_values(facts: ContractFacts, pages: list[ParsedPage]) -> list[Finding]:
    """Infer missing contract fields from document text and other facts.

    Derives two fields when missing:
    1. currency: If not set, scans document text for known ISO currency codes.
       If exactly one is found, uses it and adds CURRENCY_INFERRED finding.
    2. total_value: If not set but recurring_amount, recurring_period,
       effective_date, and end_date are present, calculates the sum of all
       payments over the term with compounded annual increases.

    Modifies facts in place and returns informational findings.

    Args:
        facts: ContractFacts to enrich (modified in place).
        pages: Parsed document pages for currency detection.

    Returns:
        list[Finding]: Derivation notes (CURRENCY_INFERRED, DERIVED_TOTAL_VALUE).
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
    """Check business rules that can reject a readable document.

    These are hard constraints that make a document unacceptable even if
    it was read confidently and is the correct type:
    - Invoice: subtotal + tax must equal total (within TOLERANCE)
    - Invoice: line items must sum to subtotal (within TOLERANCE)
    - Contract: end_date must not be before effective_date
    - Both: currency must be a valid 3-letter ISO code if present

    Args:
        facts: Extracted facts (InvoiceFacts or ContractFacts).

    Returns:
        list[Finding]: Violation findings (TOTAL_MISMATCH, LINE_ITEMS_MISMATCH,
            DATE_ORDER, INVALID_CURRENCY). Empty if no violations.
    """
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
