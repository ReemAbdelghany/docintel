"""Classifier adapter: a small, cheap model reads only the start of the document."""

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior

from docintel.models.parsed import ParsedDocument
from docintel.models.values import Confidence, DocumentType
from docintel.utils.providers.llm.errors import map_provider_error
from docintel.utils.providers.llm.schemas import LlmClassification

HEAD_PAGES = 2
HEAD_CHARS = 6000


class PydanticAIClassifier:
    def __init__(self, agent: Agent[None, LlmClassification]) -> None:
        self._agent = agent

    async def classify(self, doc: ParsedDocument) -> tuple[DocumentType, Confidence]:
        head = ParsedDocument(doc.pages[:HEAD_PAGES]).numbered_text()[:HEAD_CHARS]
        try:
            result = await self._agent.run(f"<document>\n{head}\n</document>")
        except (ModelAPIError, UnexpectedModelBehavior) as exc:
            raise map_provider_error(exc) from exc
        return DocumentType(result.output.doc_type), Confidence(result.output.confidence)
