from uuid import uuid4

from docintel.models.analysis import Extraction
from docintel.models.events import DocumentSubmitted, ExtractionCompleted, ReviewRequested
from docintel.models.facts import InvoiceFacts, LineItem
from docintel.utils.providers.db.mappers import (
    event_from_json,
    event_to_json,
    extraction_from_row,
    extraction_to_row,
    facts_from_json,
    facts_to_json,
)
from tests.unit_tests.builders import REQUIRED_EVIDENCE, a_provenance, an_invoice, money


def test_invoice_facts_survive_a_json_round_trip() -> None:
    facts = InvoiceFacts(
        vendor_name="Acme",
        invoice_number="INV-1",
        issue_date=an_invoice().issue_date,
        subtotal=money("1000.00"),
        tax=None,
        total=money("1150.00"),
        line_items=(LineItem("Paper", money("1000.00")),),
    )

    facts_type, data = facts_to_json(facts)

    assert facts_from_json(facts_type, data) == facts


def test_missing_facts_stay_missing_not_defaulted() -> None:
    empty = InvoiceFacts(None, None, None, None, None, None)

    facts_type, data = facts_to_json(empty)

    assert facts_from_json(facts_type, data) == empty


def test_an_extraction_survives_the_row_round_trip() -> None:
    extraction = Extraction(1, an_invoice(), REQUIRED_EVIDENCE, a_provenance())

    assert extraction_from_row(extraction_to_row(uuid4(), extraction)) == extraction


def test_events_survive_the_outbox_round_trip() -> None:
    events = [
        DocumentSubmitted(
            document_id=uuid4(), case_id=uuid4(), filename="a.pdf", storage_uri="local://a"
        ),
        ExtractionCompleted(uuid4(), 2),
        ReviewRequested(uuid4(), ("total mismatch", "low confidence")),
    ]

    for event in events:
        assert event_from_json(type(event).__name__, event_to_json(event)) == event
