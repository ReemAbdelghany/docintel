import asyncio
from uuid import UUID, uuid4

from docintel.config import Settings
from docintel.models.errors import CorruptDocument, ProviderUnavailable
from docintel.shared.messaging import ClaimedJob, JobStore, backoff, run_worker


class FakeJobStore(JobStore):
    """Hands out one job, then records what the worker did with it."""

    def __init__(self, job: ClaimedJob, stop: asyncio.Event) -> None:
        self._job: ClaimedJob | None = job
        self._stop = stop
        self.outcome: tuple[str, float | None] | None = None

    async def claim(self, kinds: list[str]) -> ClaimedJob | None:
        job, self._job = self._job, None
        return job

    async def done(self, job_id: UUID) -> None:
        self.outcome = ("done", None)
        self._stop.set()

    async def dead(self, job_id: UUID, error: BaseException) -> None:
        self.outcome = ("dead", None)
        self._stop.set()

    async def reschedule(self, job_id: UUID, delay_seconds: float, error: BaseException) -> None:
        self.outcome = ("rescheduled", delay_seconds)
        self._stop.set()

    async def reap(self, visibility_seconds: int) -> int:
        return 0


def settings() -> Settings:
    return Settings(_env_file=None, llm_model="x", classifier_model="x", job_max_attempts=3)


async def run_one(error: Exception | None, attempts: int = 1) -> tuple[FakeJobStore, list[str]]:
    stop = asyncio.Event()
    job = ClaimedJob(uuid4(), "analyze_document", {"document_id": str(uuid4())}, attempts)
    store = FakeJobStore(job, stop)
    dead: list[str] = []

    async def handler(payload: dict[str, str]) -> None:
        if error is not None:
            raise error

    async def on_dead(job: ClaimedJob, exc: BaseException) -> None:
        dead.append(type(exc).__name__)

    await asyncio.wait_for(
        run_worker(
            store, {"analyze_document": handler}, ["analyze_document"], stop, settings(), on_dead
        ),
        timeout=5,
    )
    return store, dead


async def test_a_successful_job_is_marked_done() -> None:
    store, dead = await run_one(None)

    assert store.outcome == ("done", None)
    assert dead == []


async def test_a_transient_error_is_rescheduled_with_a_delay() -> None:
    store, dead = await run_one(ProviderUnavailable("outage"), attempts=1)

    assert store.outcome is not None
    assert store.outcome[0] == "rescheduled"
    assert store.outcome[1] and store.outcome[1] > 0
    assert dead == []


async def test_a_transient_error_gives_up_after_the_attempt_limit() -> None:
    store, dead = await run_one(ProviderUnavailable("outage"), attempts=3)

    assert store.outcome == ("dead", None)
    assert dead == ["ProviderUnavailable"]


async def test_a_permanent_error_is_never_retried() -> None:
    store, dead = await run_one(CorruptDocument("bad file"))

    assert store.outcome == ("dead", None)
    assert dead == ["CorruptDocument"]


async def test_an_unexpected_exception_is_a_bug_not_an_outage() -> None:
    store, dead = await run_one(KeyError("boom"))

    assert store.outcome == ("dead", None)
    assert dead == ["KeyError"]


def test_backoff_grows_and_is_capped() -> None:
    assert backoff(0) > 0
    assert max(backoff(1) for _ in range(20)) < min(backoff(6) for _ in range(20)) * 3
    assert backoff(30) <= 300.0 * 1.5


async def test_every_event_handler_runs_without_raising() -> None:
    """Regression: logging with an `event=` keyword collided with structlog's own argument,
    so every AnalysisAccepted and AnalysisFailed handler failed and the event was parked."""
    from docintel.models.events import AnalysisAccepted, AnalysisFailed
    from docintel.shared.messaging import build_event_handlers
    from tests.unit_tests.fakes import Pipeline

    pipeline = Pipeline()
    handlers = build_event_handlers(lambda: pipeline.uow(), pipeline.start)

    for event in (AnalysisAccepted(uuid4(), 1), AnalysisFailed(uuid4(), "boom")):
        for handler in handlers[type(event).__name__]:
            await handler(event)
