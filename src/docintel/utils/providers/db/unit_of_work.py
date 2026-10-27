"""One transaction: aggregate state, queued jobs and outbox events commit together."""

from typing import Self

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from docintel.models.errors import InvariantViolated, TransientError
from docintel.models.events import DomainEvent
from docintel.shared.ports import AnalysisRepository, CaseRepository, JobQueue
from docintel.utils.providers.db.mappers import event_to_json
from docintel.utils.providers.db.repositories import SqlAnalysisRepository, SqlCaseRepository
from docintel.utils.providers.db.tables import OutboxRow
from docintel.utils.providers.queue.sql_job_queue import SqlJobQueue


class SqlUnitOfWork:
    analyses: AnalysisRepository
    cases: CaseRepository
    jobs: JobQueue

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def __aenter__(self) -> Self:
        self._session = self._sessions()
        self._analyses = SqlAnalysisRepository(self._session)
        self._cases = SqlCaseRepository(self._session)
        self.analyses, self.cases = self._analyses, self._cases
        self.jobs = SqlJobQueue(self._session)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if exc and exc[0] is not None:
            await self._session.rollback()
        await self._session.close()

    async def commit(self) -> None:
        try:
            await self._analyses.flush_changes()
            await self._cases.flush_changes()
            events: list[DomainEvent] = []
            for analysis in self._analyses.seen.values():
                events.extend(analysis.pull_events())
            for case in self._cases.seen.values():
                events.extend(case.pull_events())
            for event in events:
                self._session.add(
                    OutboxRow(event_type=type(event).__name__, payload=event_to_json(event))
                )
            await self._session.commit()  # state, events and jobs commit together
        except StaleDataError as exc:  # another worker changed the row: retry the job
            await self._session.rollback()
            raise TransientError("concurrent update, retry") from exc
        except IntegrityError as exc:
            await self._session.rollback()
            raise InvariantViolated(f"constraint violated: {exc.orig}") from exc
