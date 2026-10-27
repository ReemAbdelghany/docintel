import logging

import structlog

NOISY_LOGGERS = ("docling", "docling_core", "httpx", "httpcore", "huggingface_hub", "transformers")
QUIET_PATHS = ("GET /healthz", "GET /readyz", "GET /v1alpha1/documents/")


class QuietPolling(logging.Filter):
    """Drop successful access-log lines for health checks and status polling.

    uvicorn passes (client, method, path, http_version, status_code) as the record's args.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) != 5:
            return True
        _client, method, path, _version, status = args
        return not (status == 200 and f"{method} {path}".startswith(QUIET_PATHS))


def configure_logging(level: str) -> None:
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
