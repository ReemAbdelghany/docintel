"""Job worker loop, retry policy and the event handler table. No SQL lives here."""

import asyncio
import contextlib
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

import structlog

from docintel.config import Settings
from docintel.models.errors import PermanentError, TransientError
from docintel.models.events import DocumentParsed, DocumentSubmitted, DomainEvent
from docintel.shared.ports import UnitOfWork
from docintel.shared.use_cases.process_document import StartAnalysis

log = structlog.get_logger()

Handler = Callable[[dict[str, str]], Awaitable[None]]
EventHandler = Callable[[DomainEvent], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: UUID
    kind: str
    payload: dict[str, str]
    attempts: int


class JobStore:
    """Port for claiming and finishing jobs. Implemented in utils/providers/queue."""

    async def claim(self, kinds: list[str]) -> ClaimedJob | None:
        raise NotImplementedError

    async def done(self, job_id: UUID) -> None:
        raise NotImplementedError

    async def dead(self, job_id: UUID, error: BaseException) -> None:
        raise NotImplementedError

    async def reschedule(self, job_id: UUID, delay_seconds: float, error: BaseException) -> None:
        raise NotImplementedError

    async def reap(self, visibility_seconds: int) -> int:
        raise NotImplementedError


DeadLetterHandler = Callable[[ClaimedJob, BaseException], Awaitable[None]]


def backoff(attempt: int, base: float = 2.0, cap: float = 300.0) -> float:
    """Exponential delay with jitter (jitter is not security)."""
    return float(min(cap, base * 2**attempt) * random.uniform(0.5, 1.5))  # noqa: S311


async def sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def run_worker(
    store: JobStore,
    handlers: dict[str, Handler],
    kinds: list[str],
    stop: asyncio.Event,
    cfg: Settings,
    on_dead: DeadLetterHandler,
) -> None:
    """Claim and run jobs until stopped. Retries only what is worth retrying."""
    while not stop.is_set():
        job = await store.claim(kinds)
        if job is None:
            await sleep_or_stop(stop, cfg.poll_seconds)
            continue
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            job_id=str(job.id), job_kind=job.kind, document_id=job.payload.get("document_id")
        )
        try:
            await handlers[job.kind](job.payload)
            await store.done(job.id)
            log.info("job_done", attempts=job.attempts)
        except TransientError as exc:
            if job.attempts >= cfg.job_max_attempts:
                await store.dead(job.id, exc)
                await on_dead(job, exc)
            else:
                delay = backoff(job.attempts)
                await store.reschedule(job.id, delay, exc)
                log.warning(
                    "job_retry_scheduled",
                    attempts=job.attempts,
                    delay_s=round(delay, 1),
                    error=type(exc).__name__,
                )
        except PermanentError as exc:
            await store.dead(job.id, exc)
            await on_dead(job, exc)
        except Exception as exc:  # a bug, not an outage: do not retry blindly
            log.exception("job_crashed")
            await store.dead(job.id, exc)
            await on_dead(job, exc)
    structlog.contextvars.clear_contextvars()


async def run_reaper(store: JobStore, stop: asyncio.Event, cfg: Settings) -> None:
    """Return jobs from crashed workers to the queue. Safe because every use case is idempotent."""
    while not stop.is_set():
        reaped = await store.reap(cfg.job_visibility_seconds)
        if reaped:
            log.warning("jobs_reaped", count=reaped)
        await sleep_or_stop(stop, max(cfg.poll_seconds * 10, 5.0))


def build_event_handlers(
    uow_factory: Callable[[], UnitOfWork], start_analysis: StartAnalysis
) -> dict[str, list[EventHandler]]:
    """The table the outbox relay uses to turn events into effects. Handlers are idempotent."""

    async def on_submitted(event: DomainEvent) -> None:
        if not isinstance(event, DocumentSubmitted):
            raise TypeError(f"expected DocumentSubmitted, got {type(event).__name__}")
        await start_analysis(event)

    async def enqueue_analysis(event: DomainEvent) -> None:
        if not isinstance(event, DocumentParsed):
            raise TypeError(f"expected DocumentParsed, got {type(event).__name__}")
        async with uow_factory() as uow:
            await uow.jobs.enqueue(
                "analyze_document",
                {"document_id": str(event.document_id)},
                dedupe_key=f"analyze:{event.document_id}",
            )
            await uow.commit()

    async def log_processed(event: DomainEvent) -> None:
        log.info(
            "analysis_finished", event=type(event).__name__, document_id=str(event.document_id)
        )

    return {
        "DocumentSubmitted": [on_submitted],
        "DocumentParsed": [enqueue_analysis],
        "AnalysisAccepted": [log_processed],
        "AnalysisFailed": [log_processed],
        # ReviewRequested gets its handler with the review context (M10)
    }
