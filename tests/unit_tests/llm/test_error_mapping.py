import pytest
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior

from docintel.models.errors import (
    ExtractionFailed,
    PermanentError,
    ProviderRejected,
    ProviderUnavailable,
    RateLimited,
    TransientError,
)
from docintel.utils.providers.llm.errors import map_provider_error


@pytest.mark.parametrize(
    ("status", "expected"),
    [(429, RateLimited), (503, ProviderUnavailable), (500, ProviderUnavailable)],
)
def test_transient_http_errors_are_retryable(status: int, expected: type[Exception]) -> None:
    mapped = map_provider_error(ModelHTTPError(status, "model", "body"))

    assert isinstance(mapped, expected)
    assert isinstance(mapped, TransientError)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410])
def test_client_errors_are_never_retried(status: int) -> None:
    mapped = map_provider_error(ModelHTTPError(status, "model", "body"))

    assert isinstance(mapped, ProviderRejected)
    assert isinstance(mapped, PermanentError)


def test_connection_errors_are_transient() -> None:
    assert isinstance(map_provider_error(ModelAPIError("model", "timeout")), ProviderUnavailable)


def test_exhausted_schema_retries_are_permanent() -> None:
    assert isinstance(map_provider_error(UnexpectedModelBehavior("bad output")), ExtractionFailed)
