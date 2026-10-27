"""Optional distributed tracing via Pydantic Logfire.

This module provides optional tracing integration with Pydantic Logfire for
observability of the document processing pipeline. When enabled, it creates
spans for each document processing operation, including LLM calls with token
counts and costs.

Tracing is controlled by the `DOCINTEL_LOGFIRE_TOKEN` environment variable:
- If set: tracing is enabled, prompts and document text are sent to Logfire
- If not set: tracing is disabled (no-op context managers returned)

⚠️ WARNING: When tracing is enabled, document content and prompts are sent to
Logfire. Only use with synthetic/test documents in development environments.
"""

import logging
from contextlib import AbstractContextManager, nullcontext

import logfire

from docintel.config import get_settings

logger = logging.getLogger(__name__)

# Global flag indicating whether tracing is enabled
_enabled = False


def initialize_tracing() -> None:
    """Initialize Logfire tracing if token is configured.

    Reads the Logfire token from settings. If a token is present, configures
    Logfire with the service name "docintel" and instruments Pydantic AI to
    automatically create spans for each model call with token usage and cost.

    This function is called once at application startup via the FastAPI lifespan.
    """
    global _enabled
    token = get_settings().logfire_token.get_secret_value()
    if not token:
        return
    logfire.configure(token=token, service_name="docintel", console=False)
    logfire.instrument_pydantic_ai()  # one span per model call, with tokens and cost
    _enabled = True
    logger.info("Tracing to Logfire is on")


def document_span(document_id: str, filename: str) -> AbstractContextManager[object]:
    """Create a parent span for document processing.

    Returns a context manager that creates a Logfire span named "process_document"
    with the document ID and filename as attributes. All operations within this
    context (classification, extraction, verification) will be nested under this
    span.

    If tracing is not enabled, returns a null context manager that does nothing.

    Args:
        document_id: Unique identifier for the document being processed.
        filename: Original filename of the document.

    Returns:
        AbstractContextManager: Context manager for the document processing span.
            Use as `async with document_span(...):` or `with document_span(...):`.
    """
    if not _enabled:
        return nullcontext()
    return logfire.span("process_document", document_id=document_id, filename=filename)
