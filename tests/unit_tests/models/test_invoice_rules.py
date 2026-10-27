from datetime import date
from decimal import Decimal

from docintel.models.analysis import Finding
from docintel.models.facts import InvoiceFacts, LineItem
from docintel.models.rules import InvoiceRules
from tests.unit_tests.builders import an_invoice, money


def codes(findings: list[Finding]) -> list[str]:
    return [f.code for f in findings]


def invoice(**changes: object) -> InvoiceFacts:
    base = an_invoice()
    values = {
        "vendor_name": base.vendor_name,
        "invoice_number": base.invoice_number,
        "issue_date": base.issue_date,
        "subtotal": base.subtotal,
        "tax": base.tax,
        "total": base.total,
        "line_items": base.line_items,
    }
    values.update(changes)
    return InvoiceFacts(**values)  # type: ignore[arg-type]


def test_a_consistent_invoice_has_no_findings() -> None:
    assert InvoiceRules(today=lambda: date(2026, 2, 1)).check(an_invoice()) == []


def test_total_that_does_not_add_up_is_blocking() -> None:
    findings = InvoiceRules().check(invoice(total=money("1200.00")))

    assert codes(findings) == ["TOTAL_MISMATCH"]
    assert findings[0].blocking


def test_a_one_cent_rounding_difference_is_tolerated() -> None:
    assert InvoiceRules().check(invoice(total=money("1150.01"))) == []


def test_line_items_that_do_not_sum_to_the_subtotal_are_blocking() -> None:
    items = (LineItem("a", money("400.00")), LineItem("b", money("500.00")))

    assert "LINE_ITEMS_MISMATCH" in codes(InvoiceRules().check(invoice(line_items=items)))


def test_each_missing_required_fact_is_reported() -> None:
    findings = InvoiceRules().check(invoice(vendor_name=None, total=None))

    assert sorted(f.field or "" for f in findings if f.code == "MISSING_REQUIRED") == [
        "total",
        "vendor_name",
    ]


def test_a_future_date_is_advisory_not_blocking() -> None:
    findings = InvoiceRules(today=lambda: date(2026, 1, 1)).check(an_invoice())

    assert codes(findings) == ["FUTURE_DATE"]
    assert not findings[0].blocking


def test_amounts_use_decimals_not_floats() -> None:
    items = tuple(LineItem("x", money("0.10")) for _ in range(3))
    facts = invoice(
        subtotal=money("0.30"), tax=money("0.00"), total=money("0.30"), line_items=items
    )

    assert InvoiceRules(tolerance=Decimal("0")).check(facts) == []
