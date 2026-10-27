"""Optional tracing to Pydantic Logfire, so AgentCanvas can draw a document's agent workflow.

Off unless DOCINTEL_LOGFIRE_TOKEN is set. When on, prompts and document text are sent to Logfire,
so use synthetic documents only.
"""

import logging
from contextlib import AbstractContextManager, nullcontext

import logfire

from docintel.config import get_settings

logger = logging.getLogger(__name__)

_enabled = False


def initialize_tracing() -> None:
    global _enabled
    token = get_settings().logfire_token.get_secret_value()
    if not token:
        return
    logfire.configure(token=token, service_name="docintel", console=False)
    logfire.instrument_pydantic_ai()  # one span per model call, with tokens and cost
    _enabled = True
    logger.info("Tracing to Logfire is on")


def document_span(document_id: str, filename: str) -> AbstractContextManager[object]:
    """A parent span: everything inside it (classify, extract) lands in one trace per document."""
    if not _enabled:
        return nullcontext()
    return logfire.span("process_document", document_id=document_id, filename=filename)
