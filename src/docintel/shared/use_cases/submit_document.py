"""Intake: accept an uploaded file, idempotently."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from docintel.models.errors import PayloadTooLarge
from docintel.shared.ports import BlobStore, UnitOfWork

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    document_id: UUID
    duplicate: bool


class SubmitDocument:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], blobs: BlobStore) -> None:
        self._uow, self._blobs = uow_factory, blobs

    async def __call__(self, case_id: UUID, filename: str, content: bytes) -> SubmissionResult:
        if len(content) > MAX_UPLOAD_BYTES:
            raise PayloadTooLarge(f"upload exceeds {MAX_UPLOAD_BYTES} bytes")
        digest = hashlib.sha256(content).hexdigest()
        uri = await self._blobs.put(f"raw/{case_id}/{digest}", content)  # content-addressed
        async with self._uow() as uow:
            case = await uow.cases.get(case_id)
            submitted, created = case.submit(filename, digest, uri)
            await uow.commit()  # emits DocumentSubmitted only if the document is new
        return SubmissionResult(submitted.id, duplicate=not created)
