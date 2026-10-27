"""Enqueue jobs inside the caller's transaction. Enqueue twice, run once."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from docintel.utils.providers.db.tables import JobRow


class SqlJobQueue:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        kind: str,
        payload: dict[str, str],
        dedupe_key: str,
        run_at: datetime | None = None,
    ) -> None:
        stmt = (
            pg_insert(JobRow)
            .values(
                id=uuid4(),
                kind=kind,
                payload=payload,
                dedupe_key=dedupe_key,
                run_at=run_at or func.now(),
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
        )
        await self._session.execute(stmt)
