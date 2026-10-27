"""FastAPI entrypoint."""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from docintel.bootstrap import Container, build_container
from docintel.config import Settings
from docintel.models.errors import (
    DomainError,
    IllegalTransition,
    InvalidValue,
    InvariantViolated,
    NotFound,
    PayloadTooLarge,
)
from docintel.routers.router import api_router, health_router
from docintel.worker import ALL_KINDS, start_background_tasks

STATUS: dict[type[DomainError], int] = {
    NotFound: 404,
    InvalidValue: 422,
    IllegalTransition: 409,
    InvariantViolated: 409,
    PayloadTooLarge: 413,
}


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(message)s")
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

    app.include_router(health_router)
    app.include_router(api_router)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("docintel.main:app", host="127.0.0.1", port=8000)
