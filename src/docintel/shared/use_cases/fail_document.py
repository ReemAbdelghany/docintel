"""Make sure a dead job always leaves its document in a visible terminal state."""

from collections.abc import Callable
from uuid import UUID

from docintel.models.errors import IllegalTransition, NotFound
from docintel.shared.ports import UnitOfWork


class FailDocument:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow = uow_factory

    async def __call__(self, document_id: UUID, reason: str) -> None:
        async with self._uow() as uow:
            try:
                analysis = await uow.analyses.get(document_id)
                analysis.fail(reason[:500])
            except (NotFound, IllegalTransition):
                return  # unknown or already decided: nothing to record
            await uow.commit()
