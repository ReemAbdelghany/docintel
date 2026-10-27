"""FastAPI entrypoint."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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

# A refused or dropped connection is an outage. Other database errors (a missing table, a bad
# query) are bugs and must stay visible as 500s.
CONNECTION_ERRORS = (OSError, OperationalError, InterfaceError)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize every provider once, on startup."""
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
    """A refused or dropped database connection is an outage, not a bug: tell clients to retry."""
    logger.error("dependency unavailable: %s", type(exc).__name__)
    return JSONResponse(
        status_code=503, headers={"Retry-After": "5"}, content={"detail": "database unavailable"}
    )


@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
async def readyz(response: Response) -> dict[str, str]:
    try:
        async with get_async_session()() as session:
            await session.execute(text("SELECT 1"))
    except CONNECTION_ERRORS:
        response.status_code = 503
        return {"status": "unavailable", "database": "down"}
    return {"status": "ok", "database": "up"}


def main() -> None:
    uvicorn.run("docintel.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
