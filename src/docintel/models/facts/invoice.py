"""Invoice facts, free of any LLM concern."""

from dataclasses import dataclass
from datetime import date
from typing import ClassVar

from docintel.models.values import Money


@dataclass(frozen=True, slots=True)
class LineItem:
    description: str
    amount: Money


@dataclass(frozen=True, slots=True)
class InvoiceFacts:
    """A missing fact is None, never a default."""

    vendor_name: str | None
    invoice_number: str | None
    issue_date: date | None
    subtotal: Money | None
    tax: Money | None
    total: Money | None
    line_items: tuple[LineItem, ...] = ()
    REQUIRED: ClassVar[tuple[str, ...]] = ("vendor_name", "invoice_number", "issue_date", "total")
