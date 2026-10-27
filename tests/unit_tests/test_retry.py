import pytest
from pydantic_ai.exceptions import ModelHTTPError

from docintel.shared.errors import ProviderRejected, ProviderUnavailable
from docintel.utils.common.retry import with_retries


def http_error(status: int) -> ModelHTTPError:
    return ModelHTTPError(status_code=status, model_name="m", body=None)


async def test_a_fallback_chain_where_every_model_is_overloaded_is_retried() -> None:
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
    async def call() -> str:
        raise ExceptionGroup("all models failed", [http_error(503)])

    with pytest.raises(ProviderUnavailable):
        await with_retries(call, attempts=2, base=0)


async def test_a_chain_failing_only_with_client_errors_is_rejected_without_retries() -> None:
    calls = 0

    async def call() -> str:
        nonlocal calls
        calls += 1
        raise ExceptionGroup("all models failed", [http_error(401), http_error(404)])

    with pytest.raises(ProviderRejected):
        await with_retries(call, attempts=5, base=0)
    assert calls == 1
