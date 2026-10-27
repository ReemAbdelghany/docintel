"""FastAPI application entrypoint for the Document Intelligence service.

This module creates and configures the FastAPI application, including:
- Lifespan management for provider initialization/cleanup
- Global exception handlers for database connectivity issues
- Health check endpoints (/healthz, /readyz)
- API router inclusion (v1alpha1)

The lifespan context manager initializes all providers (database, storage, LLM,
parser, tracing) once at startup and cleanly shuts them down. Database
connection errors are treated as service outages (503) rather than bugs (500).
"""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import InterfaceError, OperationalError

from docintel.config import VERSION, get_settings
from docintel.routers.v1alpha1.components.crud import interrupt_unfinished
from docintel.routers.v1alpha1.router import v1alpha1_router
from docintel.utils.common.logging_config import configure_logging
from docintel.utils.providers.llm_provider import initialize_llm
from docintel.utils.providers.parser_provider import initialize_parser
from docintel.utils.providers.pg_database_provider import (
    close_engine,
    get_async_session,
    initialize_engine,
)
from docintel.utils.providers.storage_provider import initialize_storage
from docintel.utils.providers.tracing_provider import initialize_tracing

logger = logging.getLogger(__name__)

# A refused or dropped connection is an outage. Other database errors (a missing
# table, a bad query) are bugs and must stay visible as 500s.
CONNECTION_ERRORS = (OSError, OperationalError, InterfaceError)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: initialize providers on startup, cleanup on shutdown.

    Initializes all providers in order:
    1. Logging configuration
    2. Tracing (Logfire)
    3. Database engine and session factory
    4. Storage backend (local/S3)
    5. LLM agents (classifier, extractors)
    6. Document parser (Docling)

    Also flags any documents stuck in PROCESSING from a previous run as
    NEEDS_REVIEW so they can be manually reprocessed.

    On shutdown, disposes the database engine connection pool.

    Args:
        app: FastAPI application instance.

    Yields:
        None: Control passes to the application during yield.
    """
    configure_logging(get_settings().log_level)
    initialize_tracing()
    initialize_engine()
    initialize_storage()
    initialize_llm()
    initialize_parser()
    try:
        flagged = await interrupt_unfinished()
        if flagged:
            logger.warning("flagged %s interrupted documents for review", flagged)
    except CONNECTION_ERRORS:
        logger.warning("database not reachable at startup, continuing")
    yield
    await close_engine()


app = FastAPI(
    title="Document Intelligence",
    description="Upload contracts and invoices; get structured, verified data or a review task.",
    version=VERSION,
    lifespan=lifespan,
)
app.include_router(v1alpha1_router)


@app.exception_handler(OSError)
@app.exception_handler(OperationalError)
@app.exception_handler(InterfaceError)
async def on_dependency_down(request: Request, exc: Exception) -> JSONResponse:
    """Handle database connectivity failures as service outages (503).

    A refused or dropped database connection is treated as an infrastructure
    outage, not an application bug. Returns 503 with Retry-After header so
    clients can back off and retry.

    Args:
        request: The incoming request.
        exc: The connection-related exception.

    Returns:
        JSONResponse: 503 with error detail and Retry-After: 5 header.
    """
    """A refused or dropped database connection is an outage, not a bug: tell clients to retry."""
    logger.error("dependency unavailable: %s", type(exc).__name__)
    return JSONResponse(
        status_code=503, headers={"Retry-After": "5"}, content={"detail": "database unavailable"}
    )


@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    """Liveness probe: always returns ok if the process is running.

    Used by orchestration systems (Kubernetes, Docker) to determine if the
    container should be restarted. Does not check dependencies.

    Returns:
        dict: {"status": "ok"}
    """
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
async def readyz(response: Response) -> dict[str, str]:
    """Readiness probe: checks database connectivity.

    Used by orchestration systems to determine if the service can handle
    traffic. Returns 503 if the database is unreachable.

    Args:
        response: FastAPI response object for setting status code.

    Returns:
        dict: {"status": "ok", "database": "up"} or
              {"status": "unavailable", "database": "down"} with 503 status.
    """
    try:
        async with get_async_session()() as session:
            await session.execute(text("SELECT 1"))
    except CONNECTION_ERRORS:
        response.status_code = 503
        return {"status": "unavailable", "database": "down"}
    return {"status": "ok", "database": "up"}


def main() -> None:
    """Run the API server with uvicorn.

    Pass --reload to enable auto-reload on code changes during development.
    The reload directory is set to the package root (src/docintel).

    Command line usage:
        python -m docintel.main [--reload]
    """
    """Run the API. Pass --reload to restart on code changes while developing."""
    reload = "--reload" in sys.argv[1:]
    uvicorn.run(
        "docintel.main:app",
        host="127.0.0.1",
        port=8000,
        reload=reload,
        reload_dirs=[str(Path(__file__).resolve().parent)] if reload else None,
    )


if __name__ == "__main__":
    main()
