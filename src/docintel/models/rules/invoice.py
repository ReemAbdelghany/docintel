"""Deterministic business rules for invoices. A failed rule is a finding, never an exception."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

from docintel.models.analysis import Finding, Severity
from docintel.models.facts import Facts, InvoiceFacts


class InvoiceRules:
    def __init__(
        self,
        today: Callable[[], date] = date.today,
        tolerance: Decimal = Decimal("0.01"),
    ) -> None:
        self._today, self._tol = today, tolerance

    def check(self, facts: Facts) -> list[Finding]:
        if not isinstance(facts, InvoiceFacts):
            return [Finding("WRONG_FACTS_TYPE", Severity.BLOCKING, message=type(facts).__name__)]
        out: list[Finding] = []
        for name in InvoiceFacts.REQUIRED:
            if getattr(facts, name) is None:
                out.append(Finding("MISSING_REQUIRED", Severity.BLOCKING, name))
        if facts.line_items and facts.subtotal:
            items = sum((i.amount.amount for i in facts.line_items), Decimal(0))
            if abs(items - facts.subtotal.amount) > self._tol:
                out.append(
                    Finding(
                        "LINE_ITEMS_MISMATCH",
                        Severity.BLOCKING,
                        "subtotal",
                        f"line items add up to {items} but the subtotal is {facts.subtotal.amount}",
                    )
                )
        if facts.subtotal and facts.tax and facts.total:
            expected = facts.subtotal.amount + facts.tax.amount
            if abs(expected - facts.total.amount) > self._tol:
                out.append(
                    Finding(
                        "TOTAL_MISMATCH",
                        Severity.BLOCKING,
                        "total",
                        f"subtotal plus tax is {expected} but the total is {facts.total.amount}",
                    )
                )
        if facts.issue_date and facts.issue_date > self._today():
            out.append(Finding("FUTURE_DATE", Severity.ADVISORY, "issue_date"))
        return out
