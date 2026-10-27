import logging

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from docintel.config import get_settings

logger = logging.getLogger(__name__)

engine: AsyncEngine | None = None
async_session: async_sessionmaker | None = None  # type: ignore[type-arg]


def initialize_engine() -> None:
    """Create the async engine and session factory once, at startup."""
    global engine, async_session
    if engine is None:
        logger.info("Initializing database engine")
        engine = create_async_engine(get_settings().database_url, echo=False, pool_pre_ping=True)
    if async_session is None:
        async_session = async_sessionmaker(engine, expire_on_commit=False)


def get_async_session() -> async_sessionmaker:  # type: ignore[type-arg]
    if async_session is None:
        initialize_engine()
    assert async_session is not None  # noqa: S101 - set by initialize_engine
    return async_session


async def close_engine() -> None:
    global engine, async_session
    if engine is not None:
        await engine.dispose()
    engine = async_session = None
