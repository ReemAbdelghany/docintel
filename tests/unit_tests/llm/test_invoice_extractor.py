from datetime import date
from decimal import Decimal

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from docintel.models.errors import ExtractionFailed
from docintel.models.parsed import Page, ParsedDocument
from docintel.models.values import Money
from docintel.utils.providers.llm.agents import make_agent
from docintel.utils.providers.llm.invoice_extractor import PydanticAIInvoiceExtractor
from docintel.utils.providers.llm.mappers import invoice_to_domain
from docintel.utils.providers.llm.prompts import INVOICE_PROMPT_V1
from docintel.utils.providers.llm.schemas import LlmInvoice

CANNED = {
    "vendor_name": "Nile Supplies",
    "invoice_number": "INV-204",
    "issue_date": "2026-09-30",
    "currency": "EGP",
    "subtotal": "1000.00",
    "tax": "140.00",
    "total": "1140.00",
    "line_items": [{"description": "Desk", "amount": "1000.00"}],
    "evidence": [{"field": "total", "page": 1, "quote": "Total EGP 1140.00"}],
}


def a_parsed_invoice() -> ParsedDocument:
    return ParsedDocument((Page(1, "Nile Supplies INV-204 Total EGP 1140.00"),))


def agent_and_extractor(
    mode: str = "tool",
) -> tuple[Agent[None, LlmInvoice], PydanticAIInvoiceExtractor]:
    agent = make_agent(TestModel(), mode, LlmInvoice, INVOICE_PROMPT_V1)
    return agent, PydanticAIInvoiceExtractor(agent, "test-model")


async def test_extractor_maps_llm_output_to_domain() -> None:
    agent, extractor = agent_and_extractor()
    with agent.override(model=TestModel(custom_output_args=CANNED)):
        outcome = await extractor.extract(a_parsed_invoice())

    assert outcome.facts.total == Money(Decimal("1140.00"), "EGP")
    assert outcome.facts.issue_date == date(2026, 9, 30)
    assert outcome.evidence[0].field == "total"
    assert outcome.provenance.prompt_version == "invoice-v1"
    assert outcome.provenance.model == "test-model"


async def test_prompted_output_mode_builds_a_working_agent() -> None:
    agent, extractor = agent_and_extractor("prompted")
    with agent.override(model=TestModel(custom_output_text='{"vendor_name": "Nile"}')):
        outcome = await extractor.extract(a_parsed_invoice())

    assert outcome.facts.vendor_name == "Nile"


async def test_a_model_that_never_returns_valid_output_becomes_extraction_failed() -> None:
    agent, extractor = agent_and_extractor("prompted")
    with (
        agent.override(model=TestModel(custom_output_text="not json at all")),
        pytest.raises(ExtractionFailed),
    ):
        await extractor.extract(a_parsed_invoice())


def test_missing_currency_leaves_money_fields_empty() -> None:
    facts, _ = invoice_to_domain(LlmInvoice(total=Decimal("10"), currency=None))

    assert facts.total is None


def test_currency_is_normalised_and_garbage_is_ignored() -> None:
    lower, _ = invoice_to_domain(LlmInvoice(total=Decimal("10"), currency="egp"))
    junk, _ = invoice_to_domain(LlmInvoice(total=Decimal("10"), currency="Egyptian pounds"))

    assert lower.total == Money(Decimal("10"), "EGP")
    assert junk.total is None
