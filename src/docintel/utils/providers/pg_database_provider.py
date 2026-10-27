"""PostgreSQL async database provider.

This module manages the SQLAlchemy async engine and session factory for the
document intelligence service. It provides lazy initialization of the database
connection pool and a clean shutdown mechanism.

The engine and session factory are created once at startup and reused throughout
the application lifecycle. Connection pooling with pre-ping is enabled to handle
stale connections gracefully.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from docintel.config import get_settings

logger = logging.getLogger(__name__)

engine: AsyncEngine | None = None
async_session: async_sessionmaker | None = None  # type: ignore[type-arg]


def initialize_engine() -> None:
    """Create the async engine and session factory once, at startup.

    Initializes the global SQLAlchemy async engine with connection pooling
    and pre-ping enabled to detect stale connections. Also creates the
    async session factory bound to the engine.

    This function is idempotent - calling it multiple times will not create
    duplicate engines or sessions. It is called automatically by
    `get_async_session()` on first use if not already initialized.

    Raises:
        Exception: Any exception from SQLAlchemy engine creation (e.g., invalid
            database URL, connection failures).
    """
    global engine, async_session
    if engine is None:
        logger.info("Initializing database engine")
        engine = create_async_engine(
            get_settings().database_url,
            echo=False,
            pool_pre_ping=True,
        )
    if async_session is None:
        async_session = async_sessionmaker(engine, expire_on_commit=False)


def get_async_session() -> async_sessionmaker:  # type: ignore[type-arg]
    """Get the async session factory, initializing it if necessary.

    Returns the global async session factory, lazily initializing the database
    engine and session factory on first call. This ensures the database
    connection is only established when actually needed.

    Returns:
        async_sessionmaker: Factory for creating new async database sessions.
            Each session should be used as an async context manager.

    Example:
        >>> async with get_async_session()() as session:
        ...     result = await session.execute(select(Document))
    """
    if async_session is None:
        initialize_engine()
    assert async_session is not None  # noqa: S101 - set by initialize_engine
    return async_session


async def close_engine() -> None:
    """Dispose of the database engine and clear global references.

    Gracefully shuts down the connection pool by disposing of the async engine.
    This should be called during application shutdown (e.g., in FastAPI lifespan)
    to release database connections and avoid connection leaks.

    After calling this function, `get_async_session()` will re-initialize
    the engine on next use.
    """
    global engine, async_session
    if engine is not None:
        await engine.dispose()
    engine = async_session = None
