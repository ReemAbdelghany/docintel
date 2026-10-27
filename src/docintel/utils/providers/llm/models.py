"""Turn a model spec string from settings into a Pydantic AI model.

'nim:<id>' is NVIDIA NIM, 'openai-compatible:<id>' uses llm_base_url, and any
other value is a native Pydantic AI model string ('anthropic:...', 'openai:...').
"""

from openai import AsyncOpenAI
from pydantic_ai import ConcurrencyLimitedModel
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from docintel.config import Settings

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
REQUEST_TIMEOUT_SECONDS = 180.0  # reasoning models answer slowly


def openai_compatible(name: str, base_url: str, api_key: str) -> OpenAIChatModel:
    client = AsyncOpenAI(
        base_url=base_url,
        api_key=api_key or "unset",
        max_retries=0,  # the agent and our worker own retries
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return OpenAIChatModel(name, provider=OpenAIProvider(openai_client=client))


def resolve_model(spec: str, settings: Settings) -> Model | str:
    match spec.split(":", 1):
        case ["nim", name]:
            key = settings.nvidia_api_key.get_secret_value()
            return openai_compatible(name, NIM_BASE_URL, key)
        case ["openai-compatible", name]:
            key = settings.llm_api_key.get_secret_value()
            return openai_compatible(name, settings.llm_base_url, key)
        case _:
            return spec


def build_model(names: list[str], settings: Settings) -> Model:
    """One concurrency-limited model per name, chained as fallbacks."""
    limited = [
        ConcurrencyLimitedModel(resolve_model(name, settings), limiter=settings.llm_concurrency)  # type: ignore[arg-type]
        for name in names
    ]
    return limited[0] if len(limited) == 1 else FallbackModel(*limited)
