"""Unit tests for the retry logic with exponential backoff.

This module tests the with_retries function which implements resilient retry
behavior for external provider calls (LLM APIs). It verifies:

- Transient failures (5xx, 429, timeouts, network errors) are retried
- Non-transient failures (4xx client errors) are rejected immediately
- ExceptionGroup handling for FallbackModel chains
- Exhausted retries result in ProviderUnavailable
- ModelTimeoutError is treated as transient (retried, not rejected)

Test helper:
- http_error(): Creates a ModelHTTPError with specified status code
"""

import pytest
from pydantic_ai.exceptions import ModelHTTPError, ModelTimeoutError

from docintel.shared.errors import ProviderRejected, ProviderUnavailable
from docintel.utils.common.retry import with_retries


def http_error(status: int) -> ModelHTTPError:
    """Create a ModelHTTPError for testing.

    Args:
        status: HTTP status code to simulate.

    Returns:
        ModelHTTPError: Error with model_name="m" and no body.
    """
    return ModelHTTPError(status_code=status, model_name="m", body=None)


async def test_a_fallback_chain_where_every_model_is_overloaded_is_retried() -> None:
    """Test that 5xx/429 errors in a FallbackModel chain trigger retries.

    The first attempt raises an ExceptionGroup with 503 (service unavailable)
    and 429 (rate limit) from two models in the fallback chain. The second
    attempt succeeds. Total calls should be 2 (initial + 1 retry).
    """
    calls = 0

    async def call() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ExceptionGroup("all models failed", [http_error(503), http_error(429)])
        return "ok"

    assert await with_retries(call, attempts=3, base=0) == "ok"
    assert calls == 2


async def test_a_chain_that_never_recovers_ends_as_unavailable() -> None:
    """Test that persistent transient failures exhaust retries and raise ProviderUnavailable.

    The call always raises 503. After the configured attempts (2), the retry
    logic gives up and raises ProviderUnavailable with a descriptive message.
    """

    async def call() -> str:
        raise ExceptionGroup("all models failed", [http_error(503)])

    with pytest.raises(ProviderUnavailable):
        await with_retries(call, attempts=2, base=0)


async def test_a_chain_failing_only_with_client_errors_is_rejected_without_retries() -> None:
    """Test that 4xx client errors (except 429) are rejected immediately without retries.

    The call raises an ExceptionGroup with 401 (unauthorized) and 404 (not found).
    These are non-transient, so ProviderRejected is raised on the first attempt
    with no retries (calls == 1).
    """
    calls = 0

    async def call() -> str:
        nonlocal calls
        calls += 1
        raise ExceptionGroup("all models failed", [http_error(401), http_error(404)])

    with pytest.raises(ProviderRejected):
        await with_retries(call, attempts=5, base=0)
    assert calls == 1


async def test_a_timeout_on_every_model_is_retried_not_rejected() -> None:
    """Test that ModelTimeoutError is treated as transient and retried.

    ModelTimeoutError (a subclass of ModelAPIError) has no HTTP status code
    but represents a transient failure. The first attempt raises an
    ExceptionGroup with two timeouts. The second attempt succeeds.
    This verifies the fix for handling timeouts in fallback chains.
    """
    calls = 0

    async def call() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            timeout = ModelTimeoutError(model_name="m", message="Request timed out.")
            raise ExceptionGroup("all models failed", [timeout, timeout])
        return "ok"

    assert await with_retries(call, attempts=3, base=0) == "ok"
    assert calls == 2
