"""Unit tests for contract-specific verification rules.

This module tests the deterministic verification logic for contract documents,
including:
- Evidence grounding and repair (ground_by_value)
- Currency inference from document text
- Total value derivation from recurring payments with annual increases
- Handling of model-provided vs. document-stated total values

Tests use a sample lease document (LEASE) and a helper function (lease())
to create ContractFacts with various overrides for different scenarios.
"""

from datetime import date
from decimal import Decimal

from docintel.routers.v1alpha1.components.document_processor import analyze
from docintel.routers.v1alpha1.components.rules import derive_contract_values
from docintel.routers.v1alpha1.schemas.document import Classification, ContractFacts, FieldEvidence
from docintel.shared.document_types import DocumentStatus, DocumentType, ParsedPage

# Sample lease document text for testing
LEASE = [
    ParsedPage(
        1,
        "This Agreement is entered into on November 1, 2026, by the parties.\n"
        "Lessor Name: Eng. Tarek Ahmed Mansour\n"
        "Lessee Company: Nexus Technology Solutions S.A.E.\n"
        "Lease Term: Three (3) Years (Nov 1, 2026 – Oct 31, 2029)\n"
        "Monthly Rent: EGP 45,000",
    )
]


def lease(**overrides: object) -> ContractFacts:
    """Create a ContractFacts instance for the sample lease with optional overrides.

    Args:
        **overrides: Fields to override in the base lease facts.

    Returns:
        ContractFacts: Lease facts with parties, dates, rent, and evidence.
    """
    values: dict[str, object] = {
        "parties": ["Eng. Tarek Ahmed Mansour", "Nexus Technology Solutions S.A.E."],
        "effective_date": date(2026, 11, 1),
        "end_date": date(2029, 10, 31),
        "recurring_amount": Decimal("45000"),
        "recurring_period": "monthly",
        "annual_increase_percent": Decimal("10"),
        "evidence": [
            FieldEvidence(field="parties", quote="Lessor Name: Eng. Tarek Ahmed Mansour"),
            FieldEvidence(field="effective_date", quote="entered into on November 1, 2026"),
        ],
    }
    return ContractFacts(**{**values, **overrides})  # type: ignore[arg-type]


async def run(facts: ContractFacts):  # type: ignore[no-untyped-def]
    """Run the full analysis pipeline on the sample lease with given facts.

    Uses stubbed classify/extract functions that return the provided facts,
    allowing testing of the verification logic in isolation.

    Args:
        facts: ContractFacts to test.

    Returns:
        Outcome: Pipeline result with status, evidence, findings.
    """

    async def classify(pages: list[ParsedPage]) -> Classification:
        return Classification(document_type=DocumentType.CONTRACT, confidence=0.98)

    async def extract(kind: DocumentType, pages: list[ParsedPage]) -> ContractFacts:
        return facts

    return await analyze(LEASE, classify, extract, min_confidence=0.7)


async def test_a_sloppy_quote_is_accepted_when_the_value_is_in_the_document() -> None:
    """Test that ungrounded quotes are repaired when the value exists in the document.

    The model provides a sloppy quote for effective_date that doesn't match
    the document text exactly. The ground_by_value step should find the
    correct value in the document and replace the quote with a grounded one.
    """
    sloppy = FieldEvidence(field="effective_date", quote="commencement date of 1 Nov 2026 (approx)")

    outcome = await run(lease(evidence=[lease().evidence[0], sloppy]))

    assert outcome.status is DocumentStatus.ACCEPTED
    effective = next(e for e in outcome.evidence if e.field == "effective_date")
    assert "November 1, 2026" in effective.quote and effective.page == 1


async def test_a_date_that_is_not_in_the_document_still_needs_review() -> None:
    """Test that a fact value not present in the document triggers NEEDS_REVIEW.

    The model extracts an effective_date (2030-05-05) that doesn't appear
    in the document text. Even with a grounded quote for parties, the
    missing evidence for effective_date should cause review.
    """
    outcome = await run(lease(effective_date=date(2030, 5, 5), evidence=[lease().evidence[0]]))

    assert outcome.status is DocumentStatus.NEEDS_REVIEW


def test_the_currency_is_inferred_when_the_document_uses_one() -> None:
    """Test currency inference when document uses a single currency code.

    The lease document mentions "EGP 45,000". derive_contract_values should
    detect EGP as the only currency code and set it on the facts.
    """
    facts = lease()

    notes = derive_contract_values(facts, LEASE)

    assert facts.currency == "EGP"
    assert "CURRENCY_INFERRED" in [n.code for n in notes]


def test_the_currency_is_left_empty_when_the_document_is_ambiguous() -> None:
    """Test currency is not inferred when multiple currencies appear.

    When the document text contains both EGP and USD, the currency should
    remain None since it's ambiguous which one applies to the contract.
    """
    facts = lease()
    mixed = [ParsedPage(1, "Rent EGP 45,000 and a deposit of USD 1,000")]

    derive_contract_values(facts, mixed)

    assert facts.currency is None


def test_the_total_value_of_a_lease_is_the_sum_of_its_payments_with_the_yearly_increase() -> None:
    """Test total value calculation for a 3-year lease with 10% annual increase.

    Monthly rent: 45,000 EGP
    Year 1: 12 * 45,000 = 540,000
    Year 2: 12 * 49,500 = 594,000 (10% increase)
    Year 3: 12 * 54,450 = 653,400 (10% increase compounded)
    Total: 1,787,400
    """
    facts = lease()

    notes = derive_contract_values(facts, LEASE)

    # 12 x 45,000 + 12 x 49,500 + 12 x 54,450
    assert facts.total_value == Decimal("1787400.00")
    assert "36 monthly payments of 45000, rising 10% a year" in notes[-1].message


def test_a_total_value_equal_to_the_monthly_rent_is_replaced_by_the_derived_total() -> None:
    """Test that a model-provided total_value matching monthly rent is corrected.

    If the model mistakenly puts the monthly rent (45,000) in total_value,
    derive_contract_values should recognize this and replace it with the
    calculated total for the full term.
    """
    facts = lease(total_value=Decimal("45000"))

    derive_contract_values(facts, LEASE)

    assert facts.total_value == Decimal("1787400.00")


def test_a_total_value_stated_in_the_document_is_kept() -> None:
    """Test that an explicitly stated total_value in the document is preserved.

    If the document states a total value (2,000,000) that differs from the
    calculated sum of payments, the document's stated value takes precedence.
    """
    facts = lease(total_value=Decimal("2000000"))

    derive_contract_values(facts, LEASE)

    assert facts.total_value == Decimal("2000000")
