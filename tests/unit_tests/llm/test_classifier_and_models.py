from pydantic_ai.models.test import TestModel

from docintel.config import Settings
from docintel.models.parsed import Page, ParsedDocument
from docintel.models.values import Confidence, DocumentType
from docintel.utils.providers.llm import make_llm_components
from docintel.utils.providers.llm.agents import make_agent
from docintel.utils.providers.llm.classifier import PydanticAIClassifier
from docintel.utils.providers.llm.models import NIM_BASE_URL, resolve_model
from docintel.utils.providers.llm.prompts import CLASSIFIER_PROMPT_V1
from docintel.utils.providers.llm.schemas import LlmClassification


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, llm_model="nim:x/y", classifier_model="nim:a/b", **overrides)  # type: ignore[arg-type]


async def test_classifier_returns_type_and_confidence() -> None:
    agent = make_agent(TestModel(), "tool", LlmClassification, CLASSIFIER_PROMPT_V1)
    classifier = PydanticAIClassifier(agent)
    canned = {"doc_type": "invoice", "confidence": 0.9}

    with agent.override(model=TestModel(custom_output_args=canned)):
        result = await classifier.classify(ParsedDocument((Page(1, "Invoice"),)))

    assert result == (DocumentType.INVOICE, Confidence(0.9))


def test_nim_spec_points_at_the_nvidia_endpoint() -> None:
    model = resolve_model("nim:nvidia/some-model", settings(nvidia_api_key="k"))

    assert model.model_name == "nvidia/some-model"
    assert str(model.base_url).startswith(NIM_BASE_URL)


def test_native_strings_pass_through_unchanged() -> None:
    assert resolve_model("anthropic:claude-x", settings()) == "anthropic:claude-x"


def test_openai_compatible_spec_uses_the_configured_base_url() -> None:
    model = resolve_model(
        "openai-compatible:local", settings(llm_base_url="http://localhost:11434/v1")
    )

    assert str(model.base_url).startswith("http://localhost:11434/v1")


def test_components_are_built_from_settings_without_any_network() -> None:
    classifier, extractors = make_llm_components(settings(), telemetry=None)  # type: ignore[arg-type]

    assert DocumentType.INVOICE in extractors
    assert classifier is not None
