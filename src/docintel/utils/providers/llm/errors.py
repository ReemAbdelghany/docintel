"""Map vendor errors onto the retry taxonomy, once, at the adapter boundary."""

from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior

from docintel.models.errors import (
    ExtractionFailed,
    ProviderRejected,
    ProviderUnavailable,
    RateLimited,
)


def map_provider_error(exc: Exception) -> Exception:
    match exc:
        case ModelHTTPError(status_code=429):
            return RateLimited(str(exc))  # transient
        case ModelHTTPError(status_code=code) if code >= 500 or code == 408:
            return ProviderUnavailable(str(exc))  # transient
        case ModelHTTPError():
            return ProviderRejected(str(exc))  # 400, 401, 403, 404, 410: configuration, never retry
        case ModelAPIError():
            return ProviderUnavailable(str(exc))  # connection errors and timeouts
        case UnexpectedModelBehavior():
            return ExtractionFailed(str(exc))  # schema retries exhausted
        case _:
            return exc
