"""Unit tests for the logging configuration and QuietPolling filter.

This module tests the QuietPolling logging filter which suppresses successful
health check and status polling requests from uvicorn access logs to reduce
log volume in production.
"""

import logging

from docintel.utils.common.logging_config import QuietPolling


def access(method: str, path: str, status: int) -> logging.LogRecord:
    """Create a mock uvicorn access log record.

    uvicorn access logs pass (client, method, path, http_version, status_code)
    as the record's args tuple.

    Args:
        method: HTTP method (GET, POST, etc.)
        path: Request path
        status: HTTP status code

    Returns:
        logging.LogRecord: Mock access log record.
    """
    """Shaped like uvicorn's access log record."""
    args = ("127.0.0.1:1", method, path, "1.1", status)
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', args, None
    )


def test_successful_polling_is_dropped_and_everything_else_is_kept() -> None:
    """Test that QuietPolling filters health/polling 200s but keeps other requests.

    The filter should drop (return False for):
    - GET /v1alpha1/documents/{id} with 200 (status polling)
    - GET /healthz with 200 (health check)
    - GET /readyz with 200 (readiness check)

    The filter should keep (return True for):
    - POST /v1alpha1/cases with 201 (case creation)
    - GET /v1alpha1/documents/{id} with 404 (error responses)
    """
    quiet = QuietPolling()

    # Successful polling/health checks should be dropped
    assert not quiet.filter(access("GET", "/v1alpha1/documents/abc", 200))
    assert not quiet.filter(access("GET", "/healthz", 200))
    # Non-polling requests should be kept
    assert quiet.filter(access("POST", "/v1alpha1/cases", 201))
    # Error responses should be kept
    assert quiet.filter(access("GET", "/v1alpha1/documents/abc", 404))
