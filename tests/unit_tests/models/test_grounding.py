from decimal import Decimal

from docintel.models.parsed import Page, ParsedDocument
from docintel.models.services import GroundingVerifier, amount_in_text, normalize
from docintel.models.values import Evidence
from tests.unit_tests.builders import an_invoice
from tests.unit_tests.fakes import PAGE_TEXT


def codes(findings: list) -> list[str]:  # type: ignore[type-arg]
    return [f.code for f in findings]


DOC = ParsedDocument((Page(1, PAGE_TEXT),))


def test_a_quote_present_on_the_page_is_grounded() -> None:
    evidence = [Evidence("total", 1, "Total 1150.00")]

    assert GroundingVerifier().verify(an_invoice(), evidence, DOC) == []


def test_quote_missing_from_the_page_is_ungrounded() -> None:
    findings = GroundingVerifier().verify(
        an_invoice(), [Evidence("total", 1, "Total: EGP 9,999")], DOC
    )

    assert codes(findings) == ["UNGROUNDED_EVIDENCE"]


def test_a_quote_on_a_page_that_does_not_exist_is_ungrounded() -> None:
    findings = GroundingVerifier().verify(
        an_invoice(), [Evidence("total", 7, "Total 1150.00")], DOC
    )

    assert codes(findings) == ["UNGROUNDED_EVIDENCE"]


def test_a_real_quote_that_does_not_contain_the_amount_is_flagged() -> None:
    findings = GroundingVerifier().verify(an_invoice(), [Evidence("total", 1, "Tax 150.00")], DOC)

    assert codes(findings) == ["VALUE_NOT_IN_QUOTE"]


def test_matching_ignores_case_spacing_and_arabic_digits() -> None:
    assert normalize("  TOTAL   ١١٥٠ ") == "total 1150"
    assert amount_in_text(Decimal("1150.00"), "الإجمالي 1,150.00")
    assert amount_in_text(Decimal("1150.00"), "Total ١١٥٠.٠٠")
