from decimal import Decimal

import pytest

from docintel.models.errors import InvalidValue
from docintel.models.values import Confidence, Money


def test_money_adds_amounts_in_the_same_currency() -> None:
    assert Money(Decimal("1.10"), "EGP") + Money(Decimal("2.20"), "EGP") == Money(
        Decimal("3.30"), "EGP"
    )


def test_money_refuses_to_add_different_currencies() -> None:
    with pytest.raises(InvalidValue):
        Money(Decimal("1"), "EGP") + Money(Decimal("1"), "USD")


@pytest.mark.parametrize("currency", ["", "EG", "EGPP", "egp", "E1P"])
def test_money_rejects_bad_currency_codes(currency: str) -> None:
    with pytest.raises(InvalidValue):
        Money(Decimal("1"), currency)


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_confidence_must_be_between_zero_and_one(value: float) -> None:
    with pytest.raises(InvalidValue):
        Confidence(value)
