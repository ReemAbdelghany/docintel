"""Intake: open an onboarding case."""

from collections.abc import Callable
from uuid import UUID, uuid4

from docintel.models.onboarding_case import OnboardingCase
from docintel.shared.ports import UnitOfWork


class CreateCase:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow = uow_factory

    async def __call__(self) -> UUID:
        case = OnboardingCase(uuid4())
        async with self._uow() as uow:
            uow.cases.add(case)
            await uow.commit()
        return case.case_id
