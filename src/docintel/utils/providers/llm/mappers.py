"""Anti-corruption layer: translate the LLM-facing schema into domain facts and evidence."""

from decimal import Decimal

from docintel.models.facts import InvoiceFacts, LineItem
from docintel.models.values import Evidence, Money
from docintel.utils.providers.llm.schemas import LlmInvoice


def _currency(raw: str | None) -> str | None:
    code = (raw or "").strip().upper()
    return code if len(code) == 3 and code.isalpha() else None


def invoice_to_domain(llm: LlmInvoice) -> tuple[InvoiceFacts, tuple[Evidence, ...]]:
    """Missing or invalid currency leaves money fields empty: absence is explicit."""
    currency = _currency(llm.currency)

    def money(value: Decimal | None) -> Money | None:
        return Money(value, currency) if value is not None and currency else None

    facts = InvoiceFacts(
        vendor_name=llm.vendor_name,
        invoice_number=llm.invoice_number,
        issue_date=llm.issue_date,
        subtotal=money(llm.subtotal),
        tax=money(llm.tax),
        total=money(llm.total),
        line_items=tuple(
            LineItem(item.description, Money(item.amount, currency))
            for item in llm.line_items
            if currency
        ),
    )
    evidence = tuple(Evidence(e.field, e.page, e.quote) for e in llm.evidence)
    return facts, evidence
