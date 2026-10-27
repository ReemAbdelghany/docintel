"""FastAPI entrypoint."""

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from docintel.bootstrap import Container, build_container
from docintel.config import Settings
from docintel.models.errors import (
    DomainError,
    IllegalTransition,
    InvalidValue,
    InvariantViolated,
    NotFound,
    PayloadTooLarge,
    ResultNotReady,
)
from docintel.routers.router import api_router, health_router
from docintel.worker import ALL_KINDS, start_background_tasks

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")  # read when the library first runs

NOISY_LOGGERS = ("docling", "docling_core", "httpx", "httpcore", "huggingface_hub", "transformers")
QUIET_PATHS = ("GET /healthz", "GET /readyz", "GET /v1alpha1/documents/")

STATUS: dict[type[DomainError], int] = {
    NotFound: 404,
    InvalidValue: 422,
    IllegalTransition: 409,
    InvariantViolated: 409,
    PayloadTooLarge: 413,
    ResultNotReady: 409,
}


class QuietPolling(logging.Filter):
    """Drop successful access-log lines for health checks and status polling.

    uvicorn passes (client, method, path, http_version, status_code) as the record's args.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) != 5:
            return True
        _client, method, path, _version, status = args
        quiet = status == 200 and f"{method} {path}".startswith(QUIET_PATHS)
        return not quiet


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(message)s")
    logging.getLogger("uvicorn.access").addFilter(QuietPolling())
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)  # library chatter, not our events
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
    )


def create_app(
    settings: Settings | None = None,
    container_factory: Callable[[Settings], Container] = build_container,
) -> FastAPI:
    """Build the app. Settings and the container load at startup, not at import."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = settings or Settings()
        configure_logging(cfg.log_level)
        container = container_factory(cfg)
        app.state.container = container
        stop = asyncio.Event()
        tasks = start_background_tasks(container, stop, ALL_KINDS) if cfg.embedded_worker else []
        try:
            yield
        finally:
            stop.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await container.engine.dispose()

    app = FastAPI(title="SME Document Intelligence Service", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def correlation_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        cid = request.headers.get("x-request-id") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=cid)
        response = await call_next(request)
        response.headers["x-request-id"] = cid
        return response

    @app.exception_handler(DomainError)
    async def on_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        status = STATUS.get(type(exc), 400)
        return JSONResponse(
            status_code=status,
            media_type="application/problem+json",
            content={
                "type": f"urn:docintel:error:{exc.code}",
                "title": exc.code.replace("_", " "),
                "status": status,
                "detail": str(exc),
                "correlation_id": structlog.contextvars.get_contextvars().get("correlation_id"),
            },
        )

    @app.exception_handler(OSError)
    @app.exception_handler(DBAPIError)
    async def on_dependency_down(request: Request, exc: Exception) -> JSONResponse:
        # A refused or dropped connection is an outage, not a bug: tell clients to retry.
        structlog.get_logger().error("dependency_unavailable", error=type(exc).__name__)
        return JSONResponse(
            status_code=503,
            media_type="application/problem+json",
            headers={"Retry-After": "5"},
            content={
                "type": "urn:docintel:error:dependency_unavailable",
                "title": "dependency unavailable",
                "status": 503,
                "detail": "a required service (database) is unavailable, retry shortly",
                "correlation_id": structlog.contextvars.get_contextvars().get("correlation_id"),
            },
        )

    app.include_router(health_router)
    app.include_router(api_router)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("docintel.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
