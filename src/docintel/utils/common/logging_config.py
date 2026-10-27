"""Logging configuration for the document intelligence service.

This module configures structured JSON logging using structlog, with special
handling for noisy third-party loggers and quiet filtering of health check
and polling endpoints to reduce log volume.

The configuration:
- Sets up structlog with ISO timestamps, log levels, and JSON output
- Silences verbose third-party libraries (docling, httpx, transformers, etc.)
- Filters out successful health check and document status polling requests
  from uvicorn access logs
"""

import logging

import structlog

# Third-party loggers that are excessively verbose at INFO level
NOISY_LOGGERS = (
    "docling",
    "docling_core",
    "httpx",
    "httpcore",
    "huggingface_hub",
    "transformers",
)

# Path prefixes for requests that should be filtered from access logs
# when they return 200 OK (health checks and status polling)
QUIET_PATHS = ("GET /healthz", "GET /readyz", "GET /v1alpha1/documents/")


class QuietPolling(logging.Filter):
    """Drop successful access-log lines for health checks and status polling.

    uvicorn passes (client, method, path, http_version, status_code) as the
    record's args tuple. This filter suppresses log records for 200 responses
    to known polling/health check endpoints.

    Attributes:
        QUIET_PATHS: Tuple of method+path prefixes to filter (e.g., "GET /healthz").
    """

    """Drop successful access-log lines for health checks and status polling.

    uvicorn passes (client, method, path, http_version, status_code) as the record's args.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter out health check and polling requests from access logs.

        Args:
            record: Log record from uvicorn access logger.

        Returns:
            bool: False to suppress the record, True to allow it.
        """
        args = record.args
        if not isinstance(args, tuple) or len(args) != 5:
            return True
        _client, method, path, _version, status = args
        return not (status == 200 and f"{method} {path}".startswith(QUIET_PATHS))


def configure_logging(level: str) -> None:
    """Configure application-wide logging.

    Sets up:
    - Basic logging with the specified level and simple message format
    - QuietPolling filter on uvicorn access logger to suppress health/polling noise
    - WARNING level for known noisy third-party loggers
    - Structlog with JSON output, ISO timestamps, and log level processor

    Args:
        level: Logging level as string (e.g., "INFO", "DEBUG", "WARNING").
            Passed to logging.basicConfig and structlog wrapper class.
    """
    logging.basicConfig(level=level, format="%(message)s")
    logging.getLogger("uvicorn.access").addFilter(QuietPolling())
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
    )
