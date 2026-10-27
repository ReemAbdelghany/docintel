"""Processing errors. Every one of them routes a document to manual review."""


class ProcessingError(Exception):
    """Base class: the pipeline could not finish this document."""


class UnsupportedFileType(ProcessingError):
    """The file extension is not a PDF or an image."""


class ParseError(ProcessingError):
    """The file could not be read."""


class ProviderUnavailable(ProcessingError):
    """The LLM provider kept failing after every retry."""


class ProviderRejected(ProcessingError):
    """The LLM provider refused the request (bad key, bad configuration)."""


class ExtractionFailed(ProcessingError):
    """The model never produced a valid structured answer."""
