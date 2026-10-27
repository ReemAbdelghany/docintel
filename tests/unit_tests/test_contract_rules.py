from datetime import date
from decimal import Decimal

from docintel.routers.v1alpha1.components.document_processor import analyze
from docintel.routers.v1alpha1.components.rules import derive_contract_values
from docintel.routers.v1alpha1.schemas.document import Classification, ContractFacts, FieldEvidence
from docintel.shared.document_types import DocumentStatus, DocumentType, ParsedPage

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
    async def classify(pages: list[ParsedPage]) -> Classification:
        return Classification(document_type=DocumentType.CONTRACT, confidence=0.98)

    async def extract(kind: DocumentType, pages: list[ParsedPage]) -> ContractFacts:
        return facts

    return await analyze(LEASE, classify, extract, min_confidence=0.7)


async def test_a_sloppy_quote_is_accepted_when_the_value_is_in_the_document() -> None:
    sloppy = FieldEvidence(field="effective_date", quote="commencement date of 1 Nov 2026 (approx)")

    outcome = await run(lease(evidence=[lease().evidence[0], sloppy]))

    assert outcome.status is DocumentStatus.ACCEPTED
    effective = next(e for e in outcome.evidence if e.field == "effective_date")
    assert "November 1, 2026" in effective.quote and effective.page == 1


async def test_a_date_that_is_not_in_the_document_still_needs_review() -> None:
    outcome = await run(lease(effective_date=date(2030, 5, 5), evidence=[lease().evidence[0]]))

    assert outcome.status is DocumentStatus.NEEDS_REVIEW


def test_the_currency_is_inferred_when_the_document_uses_one() -> None:
    facts = lease()

    notes = derive_contract_values(facts, LEASE)

    assert facts.currency == "EGP"
    assert "CURRENCY_INFERRED" in [n.code for n in notes]


def test_the_currency_is_left_empty_when_the_document_is_ambiguous() -> None:
    facts = lease()
    mixed = [ParsedPage(1, "Rent EGP 45,000 and a deposit of USD 1,000")]

    derive_contract_values(facts, mixed)

    assert facts.currency is None


def test_the_total_value_of_a_lease_is_the_sum_of_its_payments_with_the_yearly_increase() -> None:
    facts = lease()

    notes = derive_contract_values(facts, LEASE)

    # 12 x 45,000 + 12 x 49,500 + 12 x 54,450
    assert facts.total_value == Decimal("1787400.00")
    assert "36 monthly payments of 45000, rising 10% a year" in notes[-1].message


def test_a_total_value_equal_to_the_monthly_rent_is_replaced_by_the_derived_total() -> None:
    facts = lease(total_value=Decimal("45000"))

    derive_contract_values(facts, LEASE)

    assert facts.total_value == Decimal("1787400.00")


def test_a_total_value_stated_in_the_document_is_kept() -> None:
    facts = lease(total_value=Decimal("2000000"))

    derive_contract_values(facts, LEASE)

    assert facts.total_value == Decimal("2000000")
