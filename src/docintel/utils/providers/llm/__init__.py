"""LLM adapters behind the Classifier and Extractor ports."""

from collections.abc import Mapping

from docintel.config import Settings
from docintel.models.values import DocumentType
from docintel.shared.ports import Classifier, Extractor, Telemetry
from docintel.utils.providers.llm.agents import make_agent
from docintel.utils.providers.llm.classifier import PydanticAIClassifier
from docintel.utils.providers.llm.invoice_extractor import PydanticAIInvoiceExtractor
from docintel.utils.providers.llm.models import build_model
from docintel.utils.providers.llm.prompts import CLASSIFIER_PROMPT_V1, INVOICE_PROMPT_V1
from docintel.utils.providers.llm.schemas import LlmClassification, LlmInvoice


def make_llm_components(
    settings: Settings, telemetry: Telemetry
) -> tuple[Classifier, Mapping[DocumentType, Extractor]]:
    """Build the classifier and one extractor per supported document type from settings.

    Token usage is reported by the use case from each extraction's provenance, so the
    adapters stay free of telemetry; the parameter keeps the composition root uniform.
    """
    extraction_model = build_model([settings.llm_model, *settings.llm_fallbacks], settings)
    classifier_model = build_model([settings.classifier_model], settings)
    mode = settings.llm_output_mode
    classifier = PydanticAIClassifier(
        make_agent(classifier_model, mode, LlmClassification, CLASSIFIER_PROMPT_V1)
    )
    invoice = PydanticAIInvoiceExtractor(
        make_agent(extraction_model, mode, LlmInvoice, INVOICE_PROMPT_V1), settings.llm_model
    )
    return classifier, {DocumentType.INVOICE: invoice}
