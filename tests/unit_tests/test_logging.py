import logging

from docintel.main import QuietPolling


def access(method: str, path: str, status: int) -> logging.LogRecord:
    """Shaped like uvicorn's access log record."""
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", method, path, "1.1", status),
        None,
    )


def test_polling_and_health_checks_are_dropped_when_they_succeed() -> None:
    quiet = QuietPolling()

    assert not quiet.filter(access("GET", "/v1alpha1/documents/abc", 200))
    assert not quiet.filter(access("GET", "/healthz", 200))
    assert not quiet.filter(access("GET", "/readyz", 200))


def test_other_requests_and_failed_polls_are_kept() -> None:
    quiet = QuietPolling()

    assert quiet.filter(access("POST", "/v1alpha1/cases", 201))
    assert quiet.filter(access("GET", "/v1alpha1/documents/abc", 404))
    assert quiet.filter(access("GET", "/healthz", 503))


def test_records_with_unexpected_shapes_are_never_dropped() -> None:
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "plain message", None, None)

    assert QuietPolling().filter(record)
