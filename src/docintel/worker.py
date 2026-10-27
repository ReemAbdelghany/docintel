"""Background processing: job workers, the outbox relay and the reaper.

Run standalone with `python -m docintel.worker`, or embedded in the API process
(settings.embedded_worker, started from the FastAPI lifespan).
"""

import argparse
import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from uuid import UUID

import structlog

from docintel.bootstrap import Container, build_container
from docintel.config import Settings
from docintel.shared.messaging import ClaimedJob, Handler, run_reaper, run_worker
from docintel.utils.providers.queue.outbox_relay import run_relay

log = structlog.get_logger()
ALL_KINDS = ["parse_document", "analyze_document"]


def make_handlers(c: Container) -> dict[str, Handler]:
    """Thin adapters from a job payload to a use case."""

    async def parse(payload: dict[str, str]) -> None:
        await c.parse_document(UUID(payload["document_id"]))

    async def analyze(payload: dict[str, str]) -> None:
        if c.analyze_document is None:
            raise RuntimeError("LLM adapters are not configured")
        await c.analyze_document(UUID(payload["document_id"]))

    return {"parse_document": parse, "analyze_document": analyze}


def make_dead_letter(c: Container) -> Callable[[ClaimedJob, BaseException], Awaitable[None]]:
    async def on_dead(job: ClaimedJob, exc: BaseException) -> None:
        log.error("job_dead", job_id=str(job.id), kind=job.kind, error=repr(exc))
        document_id = job.payload.get("document_id")
        if document_id:
            await c.fail_document(UUID(document_id), f"{type(exc).__name__}: {exc}")

    return on_dead


def start_background_tasks(
    c: Container, stop: asyncio.Event, kinds: list[str], relay: bool = True
) -> list[asyncio.Task[None]]:
    """Start the worker pool(s), the reaper and (optionally) the outbox relay."""
    tasks = [
        asyncio.create_task(
            run_worker(c.job_store, make_handlers(c), kinds, stop, c.settings, make_dead_letter(c))
        ),
        asyncio.create_task(run_reaper(c.job_store, stop, c.settings)),
    ]
    if relay:
        tasks.append(asyncio.create_task(run_relay(c.sessions, c.event_handlers, stop, c.settings)))
    return tasks


async def main(kinds: list[str], relay: bool) -> None:
    settings = Settings()
    logging.basicConfig(level=settings.log_level)
    container = build_container(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    log.info("worker_started", kinds=kinds, relay=relay)
    await asyncio.gather(*start_background_tasks(container, stop, kinds, relay))
    await container.engine.dispose()


def cli() -> None:
    parser = argparse.ArgumentParser(description="docintel background worker")
    parser.add_argument("--kinds", nargs="+", default=ALL_KINDS, choices=ALL_KINDS)
    parser.add_argument("--no-relay", action="store_true", help="do not run the outbox relay")
    args = parser.parse_args()
    asyncio.run(main(args.kinds, relay=not args.no_relay))


if __name__ == "__main__":
    cli()
