"""Error taxonomy: infrastructure errors decide retries, domain errors decide rejections."""


class TransientError(Exception):
    """A failure worth retrying with backoff."""


class PermanentError(Exception):
    """A failure that retrying cannot fix."""


class ProviderUnavailable(TransientError):
    """The LLM or storage provider is down or timing out."""


class RateLimited(TransientError):
    """The provider asked us to slow down."""


class CorruptDocument(PermanentError):
    """The file cannot be read."""


class UnsupportedFormat(PermanentError):
    """The file type is not handled."""


class BlobNotFound(PermanentError):
    """The stored file is missing."""


class ProviderRejected(PermanentError):
    """The provider refused the request (bad key or configuration)."""


class ExtractionFailed(PermanentError):
    """The model never produced a valid structured answer."""


class DomainError(Exception):
    """A business rule was broken. Carries a stable code for API error responses."""

    code = "domain_error"


class InvalidValue(DomainError):
    code = "invalid_value"


class IllegalTransition(DomainError):
    code = "illegal_transition"


class InvariantViolated(DomainError):
    code = "invariant_violated"


class NotFound(DomainError):
    code = "not_found"


class ResultNotReady(DomainError):
    code = "result_not_ready"


class PayloadTooLarge(DomainError):
    code = "payload_too_large"
