"""LLM access through Pydantic AI.

This module provides a unified interface for interacting with Large Language Models
via Pydantic AI. It supports multiple model providers (NVIDIA NIM, OpenAI-compatible
endpoints, Anthropic, native OpenAI) with automatic fallback chains for resilience.

The provider is configured via settings using model specification strings:
- `nim:<model-id>` - NVIDIA NIM hosted models
- `openai-compatible:<model-id>` - OpenAI-compatible endpoints (e.g., vLLM, Ollama)
- `openai:<model-id>` - Native OpenAI models
- `anthropic:<model-id>` - Native Anthropic models

A fallback chain can be configured via `llm_fallbacks` setting for automatic
failover on rate limits, outages, or 4xx/5xx errors.

Agents are initialized once at startup with deterministic settings (temperature=0)
for consistent extraction results.
"""

import os

from openai import AsyncOpenAI
from pydantic_ai import Agent, PromptedOutput, ToolOutput
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from docintel.config import Settings, get_settings
from docintel.routers.v1alpha1.schemas.document import Classification, ContractFacts, InvoiceFacts
from docintel.shared.document_types import DocumentType
from docintel.utils.common.prompts import CLASSIFY, CONTRACT, INVOICE

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

# Deterministic model settings for consistent extraction (no creativity)
DETERMINISTIC: ModelSettings = {"temperature": 0.0}
# NVIDIA NIM API base URL
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"

# Global agent instances (initialized once at startup)
_classifier: Agent[None, Classification] | None = None
_extractors: dict[DocumentType, Agent[None, InvoiceFacts] | Agent[None, ContractFacts]] = {}


def openai_compatible(name: str, base_url: str, api_key: str) -> OpenAIChatModel:
    """Create an OpenAI-compatible chat model.

    Wraps an AsyncOpenAI client with Pydantic AI's OpenAI provider. Retries are
    disabled at the client level because retry logic is handled at the application
    layer via `with_retries` with custom backoff and fallback strategies.

    Args:
        name: Model identifier (e.g., "gpt-4", "nemotron-3-ultra").
        base_url: Base URL for the OpenAI-compatible API endpoint.
        api_key: API key for authentication.

    Returns:
        OpenAIChatModel: Configured Pydantic AI model ready for use in Agents.
    """
    client = AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=0)  # we own the retries
    return OpenAIChatModel(name, provider=OpenAIProvider(openai_client=client))


def resolve_model(spec: str, settings: Settings) -> Model | str:
    """Resolve a model specification string to a Pydantic AI Model.

    Parses the model specification and returns the appropriate model instance.
    Supported prefixes:
    - `nim:` - NVIDIA NIM hosted model (uses NIM_BASE_URL and NVIDIA API key)
    - `openai-compatible:` - OpenAI-compatible endpoint (uses llm_base_url and llm_api_key)
    - Any other string - passed through as-is for native provider resolution
      (e.g., "openai:gpt-4", "anthropic:claude-3-opus")

    Args:
        spec: Model specification string (e.g., "nim:nemotron-3-ultra").
        settings: Application settings containing API keys and endpoints.

    Returns:
        Model | str: Resolved Pydantic AI Model instance or native model string.
    """
    match spec.split(":", 1):
        case ["nim", name]:
            return openai_compatible(name, NIM_BASE_URL, settings.nvidia_api_key.get_secret_value())
        case ["openai-compatible", name]:
            return openai_compatible(
                name, settings.llm_base_url, settings.llm_api_key.get_secret_value()
            )
        case _:
            return spec  # 'anthropic:...', 'openai:...' and so on


def build_model(spec: str, settings: Settings) -> Model | str:
    """Build a model with fallback chain for resilience.

    Constructs a FallbackModel that tries the primary model first, then each
    fallback in order when the previous model fails due to rate limits, outages,
    or 4xx/5xx errors. The primary model is always tried first; fallbacks that
    duplicate the primary are skipped.

    Args:
        spec: Primary model specification string.
        settings: Application settings containing fallback configuration.

    Returns:
        Model | str: Single model if no fallbacks configured, otherwise a
            FallbackModel wrapping the primary and all fallbacks.
    """
    fallbacks = [s.strip() for s in settings.llm_fallbacks.split(",") if s.strip()]
    chain = [spec, *[f for f in fallbacks if f != spec]]
    if len(chain) == 1:
        return resolve_model(spec, settings)
    models = [resolve_model(s, settings) for s in chain]
    return FallbackModel(*models)


def _output[T](schema: type[T], settings: Settings) -> ToolOutput[T] | PromptedOutput[T]:
    """Create the appropriate output type based on settings.

    Args:
        schema: Pydantic model class for structured output.
        settings: Application settings containing output mode preference.

    Returns:
        ToolOutput | PromptedOutput: Output handler based on llm_output_mode setting.
            - "tool": Uses function calling / tool output (preferred for structured data)
            - "prompted": Uses prompted output with JSON schema in prompt
    """
    return ToolOutput(schema) if settings.llm_output_mode == "tool" else PromptedOutput(schema)


def initialize_llm() -> None:
    """Initialize the global classifier and extractor agents.

    Creates and configures the Pydantic AI agents for document classification
    and fact extraction (invoice/contract). Agents are configured with:
    - Deterministic model settings (temperature=0) for consistent results
    - Custom instructions/prompts for each task
    - Retry count of 2 for transient failures
    - Structured output via ToolOutput or PromptedOutput based on settings

    This function is idempotent and called automatically by get_classifier()
    and get_extractor() on first use.
    """
    global _classifier
    settings = get_settings()
    classifier_model = build_model(settings.classifier_model, settings)
    model = build_model(settings.llm_model, settings)
    _classifier = Agent(
        classifier_model,
        output_type=_output(Classification, settings),
        instructions=CLASSIFY,
        retries=2,
        model_settings=DETERMINISTIC,
    )
    _extractors[DocumentType.INVOICE] = Agent(
        model,
        output_type=_output(InvoiceFacts, settings),
        instructions=INVOICE,
        retries=2,
        model_settings=DETERMINISTIC,
    )
    _extractors[DocumentType.CONTRACT] = Agent(
        model,
        output_type=_output(ContractFacts, settings),
        instructions=CONTRACT,
        retries=2,
        model_settings=DETERMINISTIC,
    )


def get_classifier() -> Agent[None, Classification]:
    """Get the document classifier agent, initializing if necessary.

    Returns the global classifier agent for determining document type
    (invoice, contract, or other). Lazily initializes the LLM agents
    on first call.

    Returns:
        Agent[None, Classification]: Configured classifier agent.
    """
    if _classifier is None:
        initialize_llm()
    assert _classifier is not None  # noqa: S101 - set by initialize_llm
    return _classifier


def get_extractor(
    doc_type: DocumentType,
) -> Agent[None, InvoiceFacts] | Agent[None, ContractFacts]:
    """Get the fact extractor agent for a document type.

    Returns the appropriate extractor agent for the given document type.
    Lazily initializes the LLM agents on first call.

    Args:
        doc_type: Type of document to extract facts from (INVOICE or CONTRACT).

    Returns:
        Agent[None, InvoiceFacts] | Agent[None, ContractFacts]: Configured
            extractor agent for the specified document type.

    Raises:
        KeyError: If doc_type is not a supported document type.
    """
    if not _extractors:
        initialize_llm()
    return _extractors[doc_type]
