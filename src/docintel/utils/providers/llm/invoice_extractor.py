"""Invoice extractor adapter: Pydantic AI behind the Extractor port."""

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior

from docintel.models.analysis import Provenance
from docintel.models.parsed import ParsedDocument
from docintel.shared.ports import ExtractionOutcome
from docintel.utils.providers.llm.errors import map_provider_error
from docintel.utils.providers.llm.mappers import invoice_to_domain
from docintel.utils.providers.llm.prompts import INVOICE_PROMPT_VERSION, INVOICE_SCHEMA_VERSION
from docintel.utils.providers.llm.schemas import LlmInvoice


class PydanticAIInvoiceExtractor:
    def __init__(self, agent: Agent[None, LlmInvoice], model_name: str) -> None:
        self._agent, self._model_name = agent, model_name

    async def extract(self, doc: ParsedDocument) -> ExtractionOutcome:
        prompt = f"<document>\n{doc.numbered_text()}\n</document>"  # data, clearly delimited
        try:
            result = await self._agent.run(prompt)
        except (ModelAPIError, UnexpectedModelBehavior) as exc:
            raise map_provider_error(exc) from exc
        usage = result.usage
        facts, evidence = invoice_to_domain(result.output)
        return ExtractionOutcome(
            facts,
            evidence,
            Provenance(
                self._model_name,
                INVOICE_PROMPT_VERSION,
                INVOICE_SCHEMA_VERSION,
                usage.input_tokens,
                usage.output_tokens,
            ),
        )
