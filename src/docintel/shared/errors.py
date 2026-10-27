"""Processing errors for the document intelligence pipeline.

This module defines the exception hierarchy for document processing failures.
Every exception in this module inherits from `ProcessingError` and represents
a condition that routes a document to manual review (status: needs_review).

The design principle: the system prefers a missing fact and a review task over
a confidently wrong value. Any uncertainty or failure in parsing, classification,
extraction, or verification results in a ProcessingError subclass being raised,
which the pipeline catches and converts to a `needs_review` outcome.

Exception hierarchy:
- ProcessingError (base)
  - UnsupportedFileType: File extension not supported
  - ParseError: Document could not be read/parsed
  - ProviderUnavailable: LLM provider failed after all retries
  - ProviderRejected: LLM provider refused request (auth, config)
  - ExtractionFailed: Model never produced valid structured output
"""


class ProcessingError(Exception):
    """Base class: the pipeline could not finish this document.

    All document processing exceptions inherit from this class. When caught
    by the pipeline, the document is marked as `needs_review` with the
    exception message as the reason.
    """


class UnsupportedFileType(ProcessingError):
    """The file extension is not a PDF or an image.

    Raised when a document is uploaded with an unsupported file extension.
    Supported extensions: .pdf, .png, .jpg, .jpeg, .tiff
    """


class ParseError(ProcessingError):
    """The file could not be read.

    Raised when Docling fails to convert the document (corrupted file,
    password-protected PDF, unsupported format despite extension, etc.)
    or when no text could be extracted from any page.
    """


class ProviderUnavailable(ProcessingError):
    """The LLM provider kept failing after every retry.

    Raised when all retry attempts are exhausted for transient failures
    (rate limits, 5xx errors, network errors, timeouts). Indicates a
    persistent provider outage or connectivity issue.
    """


class ProviderRejected(ProcessingError):
    """The LLM provider refused the request (bad key, bad configuration).

    Raised for non-transient provider failures such as:
    - Invalid API key (401)
    - Insufficient permissions (403)
    - Model not found (404)
    - Request validation errors (400)
    - Quota exceeded (429 treated as non-transient in some contexts)
    """


class ExtractionFailed(ProcessingError):
    """The model never produced a valid structured answer.

    Raised when the model responds but the output cannot be parsed into
    the expected Pydantic schema (UnexpectedModelBehavior from Pydantic AI).
    This includes malformed JSON, missing required fields, type mismatches, etc.
    """
