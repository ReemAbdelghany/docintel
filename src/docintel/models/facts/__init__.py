"""Business definition of each document type's facts."""

from typing import ClassVar, Protocol

from docintel.models.facts.invoice import InvoiceFacts, LineItem


class Facts(Protocol):
    """Anything extracted from a document. REQUIRED names the facts that must have evidence."""

    REQUIRED: ClassVar[tuple[str, ...]]


__all__ = ["Facts", "InvoiceFacts", "LineItem"]
