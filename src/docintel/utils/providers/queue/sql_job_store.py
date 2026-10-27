"""Claim and finish jobs with FOR UPDATE SKIP LOCKED so many workers never collide."""

from uuid import UUID

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from docintel.shared.messaging import ClaimedJob, JobStore
from docintel.utils.providers.db.tables import JobRow

CLAIM = text(
    """
    UPDATE jobs SET status = 'running', locked_at = now(), attempts = attempts + 1
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'queued' AND run_at <= now() AND kind = ANY(CAST(:kinds AS text[]))
        ORDER BY run_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, kind, payload, attempts
    """
)

REAP = text(
    """
    UPDATE jobs SET status = 'queued'
    WHERE status = 'running' AND locked_at < now() - make_interval(secs => :visibility)
    """
)

RESCHEDULE = text(
    """
    UPDATE jobs SET status = 'queued', last_error = :error,
        run_at = now() + make_interval(secs => :delay)
    WHERE id = :id
    """
)


class SqlJobStore(JobStore):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def claim(self, kinds: list[str]) -> ClaimedJob | None:
        async with self._sessions() as s, s.begin():
            row = (await s.execute(CLAIM, {"kinds": kinds})).first()
        if row is None:
            return None
        return ClaimedJob(
            id=row.id,
            kind=row.kind,
            payload={k: str(v) for k, v in row.payload.items()},
            attempts=row.attempts,
        )

    async def done(self, job_id: UUID) -> None:
        async with self._sessions() as s, s.begin():
            await s.execute(update(JobRow).where(JobRow.id == job_id).values(status="done"))

    async def dead(self, job_id: UUID, error: BaseException) -> None:
        async with self._sessions() as s, s.begin():
            await s.execute(
                update(JobRow)
                .where(JobRow.id == job_id)
                .values(status="dead", last_error=repr(error)[:500])
            )

    async def reschedule(self, job_id: UUID, delay_seconds: float, error: BaseException) -> None:
        async with self._sessions() as s, s.begin():
            await s.execute(
                RESCHEDULE,
                {"id": job_id, "delay": delay_seconds, "error": repr(error)[:500]},
            )

    async def reap(self, visibility_seconds: int) -> int:
        async with self._sessions() as s, s.begin():
            result = await s.execute(REAP, {"visibility": visibility_seconds})
            return int(result.rowcount)  # type: ignore[attr-defined]
