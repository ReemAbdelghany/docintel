"""Structured-log telemetry: stage timings and LLM usage. Replaced by OpenTelemetry in M8."""

import time
from collections.abc import Iterator
from contextlib import contextmanager

import structlog

log = structlog.get_logger()


class LogTelemetry:
    @contextmanager
    def stage(self, name: str, **attrs: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            log.info(
                "stage_finished",
                stage=name,
                duration_ms=round((time.perf_counter() - started) * 1000),
                **attrs,
            )

    def llm_usage(self, model: str, input_tokens: int, output_tokens: int) -> None:
        log.info("llm_usage", model=model, input_tokens=input_tokens, output_tokens=output_tokens)

    def outcome(self, doc_type: str, status: str) -> None:
        log.info("document_outcome", doc_type=doc_type, status=status)
