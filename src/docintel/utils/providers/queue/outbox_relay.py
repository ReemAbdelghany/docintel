"""Deliver outbox events to their handlers at least once. One poison event never blocks the rest."""

import asyncio

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from docintel.config import Settings
from docintel.shared.messaging import EventHandler, sleep_or_stop
from docintel.utils.providers.db.mappers import event_from_json
from docintel.utils.providers.db.tables import OutboxRow

log = structlog.get_logger()


async def relay_once(
    sessions: async_sessionmaker[AsyncSession],
    handlers: dict[str, list[EventHandler]],
    max_attempts: int,
    batch: int = 50,
) -> int:
    """Process one batch. Returns how many rows were looked at."""
    async with sessions() as session, session.begin():
        rows = (
            (
                await session.execute(
                    select(OutboxRow)
                    .where(OutboxRow.processed_at.is_(None), OutboxRow.parked.is_(False))
                    .order_by(OutboxRow.id)
                    .limit(batch)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            try:
                event = event_from_json(row.event_type, row.payload)
                for handler in handlers.get(row.event_type, []):
                    await handler(event)  # idempotent: delivery is at least once
                row.processed_at = func.now()
            except Exception as exc:  # one poison event must not block the stream
                row.attempts += 1
                row.error = repr(exc)[:500]
                row.parked = row.attempts >= max_attempts
                log.exception("outbox_handler_failed", outbox_id=row.id, parked=row.parked)
        return len(rows)


async def run_relay(
    sessions: async_sessionmaker[AsyncSession],
    handlers: dict[str, list[EventHandler]],
    stop: asyncio.Event,
    cfg: Settings,
) -> None:
    while not stop.is_set():
        handled = await relay_once(sessions, handlers, cfg.outbox_max_attempts)
        if handled == 0:
            await sleep_or_stop(stop, cfg.poll_seconds)
