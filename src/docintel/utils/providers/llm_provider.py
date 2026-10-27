"""LLM access through Pydantic AI. The provider is chosen by a model string in the settings."""

import os

from openai import AsyncOpenAI
from pydantic_ai import Agent, PromptedOutput, ToolOutput
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from docintel.config import Settings, get_settings
from docintel.routers.v1alpha1.schemas.document import Classification, ContractFacts, InvoiceFacts
from docintel.shared.document_types import DocumentType
from docintel.utils.common.prompts import CLASSIFY, CONTRACT, INVOICE

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"

_classifier: Agent[None, Classification] | None = None
_extractors: dict[DocumentType, Agent[None, InvoiceFacts] | Agent[None, ContractFacts]] = {}


def openai_compatible(name: str, base_url: str, api_key: str) -> OpenAIChatModel:
    client = AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=0)  # we own the retries
    return OpenAIChatModel(name, provider=OpenAIProvider(openai_client=client))


def resolve_model(spec: str, settings: Settings) -> Model | str:
    """'nim:<id>' is NVIDIA NIM, 'openai-compatible:<id>' uses llm_base_url, else native."""
    match spec.split(":", 1):
        case ["nim", name]:
            return openai_compatible(name, NIM_BASE_URL, settings.nvidia_api_key.get_secret_value())
        case ["openai-compatible", name]:
            return openai_compatible(
                name, settings.llm_base_url, settings.llm_api_key.get_secret_value()
            )
        case _:
            return spec  # 'anthropic:...', 'openai:...' and so on


def _output[T](schema: type[T], settings: Settings) -> ToolOutput[T] | PromptedOutput[T]:
    return ToolOutput(schema) if settings.llm_output_mode == "tool" else PromptedOutput(schema)


def initialize_llm() -> None:
    global _classifier
    settings = get_settings()
    classifier_model = resolve_model(settings.classifier_model, settings)
    model = resolve_model(settings.llm_model, settings)
    _classifier = Agent(
        classifier_model,
        output_type=_output(Classification, settings),
        instructions=CLASSIFY,
        retries=2,
    )
    _extractors[DocumentType.INVOICE] = Agent(
        model, output_type=_output(InvoiceFacts, settings), instructions=INVOICE, retries=2
    )
    _extractors[DocumentType.CONTRACT] = Agent(
        model, output_type=_output(ContractFacts, settings), instructions=CONTRACT, retries=2
    )


def get_classifier() -> Agent[None, Classification]:
    if _classifier is None:
        initialize_llm()
    assert _classifier is not None  # noqa: S101 - set by initialize_llm
    return _classifier


def get_extractor(
    doc_type: DocumentType,
) -> Agent[None, InvoiceFacts] | Agent[None, ContractFacts]:
    if not _extractors:
        initialize_llm()
    return _extractors[doc_type]
