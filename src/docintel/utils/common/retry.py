"""Retry transient provider failures with exponential backoff and jitter."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

import httpx
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior

from docintel.shared.errors import ExtractionFailed, ProviderRejected, ProviderUnavailable

logger = logging.getLogger(__name__)


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, ModelHTTPError):
        return exc.status_code == 429 or exc.status_code >= 500
    return isinstance(exc, httpx.TransportError | TimeoutError | ConnectionError)


async def with_retries[T](
    call: Callable[[], Awaitable[T]], attempts: int, base: float = 2.0, cap: float = 30.0
) -> T:
    """Run call; retry rate limits, 5xx and network errors; map other failures to our errors."""
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except UnexpectedModelBehavior as exc:
            raise ExtractionFailed(str(exc)) from exc
        except (ModelHTTPError, httpx.TransportError, TimeoutError, ConnectionError) as exc:
            if not _is_transient(exc):
                raise ProviderRejected(str(exc)) from exc
            if attempt == attempts:
                raise ProviderUnavailable(f"gave up after {attempts} attempts: {exc}") from exc
            delay = min(cap, base**attempt) * random.uniform(0.5, 1.0)  # noqa: S311 - jitter only
            logger.warning("provider_retry attempt=%s delay=%.1fs error=%s", attempt, delay, exc)
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
