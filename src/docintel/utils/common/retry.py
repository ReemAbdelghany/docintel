"""Retry transient provider failures with exponential backoff and jitter.

This module provides a resilient retry mechanism for external provider calls
(LLM APIs, HTTP services, database connections). It implements exponential
backoff with jitter to avoid thundering herd problems and handles various
failure modes appropriately:

- Transient failures (rate limits 429, server errors 5xx, network errors, timeouts):
  Retried with exponential backoff and jitter
- Non-transient failures (client errors 4xx except 429, model behavior errors):
  Mapped to domain-specific exceptions (ProviderRejected, ExtractionFailed)
- Exhausted retries: Mapped to ProviderUnavailable

The retry logic is designed to work with Pydantic AI's FallbackModel, where
an ExceptionGroup may contain multiple failures from different models in the
fallback chain.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

import httpx
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior

from docintel.shared.errors import ExtractionFailed, ProviderRejected, ProviderUnavailable

logger = logging.getLogger(__name__)


def _is_transient(exc: Exception) -> bool:
    """Determine if an exception represents a transient failure worth retrying.

    Transient failures include:
    - HTTP 429 (rate limit) and 5xx (server errors) from ModelHTTPError
    - ModelAPIError (timeouts, connection errors without status codes)
    - httpx.TransportError (network-level failures)
    - TimeoutError and ConnectionError (built-in timeout/connection errors)

    Args:
        exc: Exception to evaluate.

    Returns:
        bool: True if the exception is transient and should be retried.
    """
    if isinstance(exc, ModelHTTPError):
        return exc.status_code == 429 or exc.status_code >= 500
    # Timeouts and dropped connections (ModelConnectionError) have no status code: retry them.
    return isinstance(exc, ModelAPIError | httpx.TransportError | TimeoutError | ConnectionError)


def _describe(exc: BaseException) -> str:
    """Create a human-readable description of an exception for logging.

    Handles ExceptionGroup by describing each contained exception. For
    ModelHTTPError, includes the model name and HTTP status code. For other
    exceptions, includes the exception type and message.

    Args:
        exc: Exception to describe.

    Returns:
        str: One-line description suitable for logging.
    """
    """One line per failed model, so an error says why every model in the chain failed."""
    if isinstance(exc, ExceptionGroup):
        return "; ".join(_describe(e) for e in exc.exceptions)
    if isinstance(exc, ModelHTTPError):
        return f"{exc.model_name}: HTTP {exc.status_code}"
    return f"{type(exc).__name__}: {exc}"


def _is_transient_failure(exc: Exception) -> bool:
    """Check if an exception (or any in an ExceptionGroup) is transient.

    Recursively checks ExceptionGroup contents to determine if at least one
    failure in the group is transient. This is used when a FallbackModel has
    exhausted all models - if any model failed transiently, we retry the
    entire chain.

    Args:
        exc: Exception or ExceptionGroup to evaluate.

    Returns:
        bool: True if the exception or any contained exception is transient.
    """
    if isinstance(exc, ExceptionGroup):
        return any(_is_transient_failure(e) for e in exc.exceptions if isinstance(e, Exception))
    return _is_transient(exc)


async def with_retries[T](
    call: Callable[[], Awaitable[T]], attempts: int, base: float = 2.0, cap: float = 30.0
) -> T:
    """Execute an async callable with retry logic for transient failures.

    Runs the provided callable, retrying on transient failures with exponential
    backoff and jitter. Non-transient failures are converted to domain-specific
    exceptions immediately. If all attempts are exhausted, raises ProviderUnavailable.

    Retry behavior:
    - Attempt 1: immediate
    - Attempt 2: base^2 * jitter (0.5-1.0) seconds
    - Attempt 3: base^3 * jitter seconds
    - ... up to cap seconds maximum

    Args:
        call: Async callable to execute (takes no arguments, returns T).
        attempts: Maximum number of attempts (including the first).
        base: Base for exponential backoff (default 2.0).
        cap: Maximum delay in seconds (default 30.0).

    Returns:
        T: Result of the successful call.

    Raises:
        ExtractionFailed: If the model exhibits unexpected behavior (e.g., invalid
            structured output).
        ProviderRejected: If a non-transient failure occurs (client errors, etc.).
        ProviderUnavailable: If all retry attempts are exhausted on transient failures.
        AssertionError: If the loop exits unexpectedly (should never happen).
    """
    """Run call; retry rate limits, 5xx and network errors; map other failures to our errors."""
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except UnexpectedModelBehavior as exc:
            raise ExtractionFailed(str(exc)) from exc
        except (
            ExceptionGroup,  # every model in the fallback chain failed
            ModelAPIError,
            httpx.TransportError,
            TimeoutError,
            ConnectionError,
        ) as exc:
            if not _is_transient_failure(exc):
                raise ProviderRejected(_describe(exc)) from exc
            if attempt == attempts:
                raise ProviderUnavailable(
                    f"gave up after {attempts} attempts: {_describe(exc)}"
                ) from exc
            delay = min(cap, base**attempt) * random.uniform(0.5, 1.0)  # noqa: S311 - jitter only
            logger.warning(
                "provider_retry attempt=%s delay=%.1fs error=%s", attempt, delay, _describe(exc)
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
