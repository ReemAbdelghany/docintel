import logging

from docintel.utils.common.logging_config import QuietPolling


def access(method: str, path: str, status: int) -> logging.LogRecord:
    """Shaped like uvicorn's access log record."""
    args = ("127.0.0.1:1", method, path, "1.1", status)
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', args, None
    )


def test_successful_polling_is_dropped_and_everything_else_is_kept() -> None:
    quiet = QuietPolling()

    assert not quiet.filter(access("GET", "/v1alpha1/documents/abc", 200))
    assert not quiet.filter(access("GET", "/healthz", 200))
    assert quiet.filter(access("POST", "/v1alpha1/cases", 201))
    assert quiet.filter(access("GET", "/v1alpha1/documents/abc", 404))
