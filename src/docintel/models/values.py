"""Value objects: frozen, validated on construction, equal by value."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from docintel.models.errors import InvalidValue


@dataclass(frozen=True, slots=True)
class Money:
    """An amount of money. Never a float; the currency is an ISO 4217 code."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if len(self.currency) != 3 or not self.currency.isalpha() or not self.currency.isupper():
            raise InvalidValue(f"bad currency: {self.currency}")

    def __add__(self, other: "Money") -> "Money":
        if other.currency != self.currency:
            raise InvalidValue("currency mismatch")
        return Money(self.amount + other.amount, self.currency)


@dataclass(frozen=True, slots=True)
class Confidence:
    """A probability between 0 and 1."""

    value: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise InvalidValue("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class Evidence:
    """The page and verbatim text that supports one extracted fact."""

    field: str
    page: int
    snippet: str


class DocumentType(StrEnum):
    LEASE = "lease"
    INVOICE = "invoice"
    CONTRACT = "contract"
    OTHER = "other"
