"""Blob storage behind one interface: local disk (default) or S3-compatible (MinIO, AWS)."""

import asyncio
from pathlib import Path
from typing import Protocol

import aioboto3

from docintel.config import Settings, get_settings


class BlobStore(Protocol):
    async def put(self, key: str, data: bytes) -> str:
        """Store bytes and return a URI that says where they live."""
        ...

    async def get(self, uri: str) -> bytes: ...


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError("storage key escapes the storage root")
        return path

    async def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        return f"local://{key}"

    async def get(self, uri: str) -> bytes:
        return await asyncio.to_thread(self._path(uri.removeprefix("local://")).read_bytes)


class S3BlobStore:
    def __init__(self, settings: Settings) -> None:
        self._endpoint, self._bucket = settings.s3_endpoint, settings.s3_bucket
        self._session = aioboto3.Session()

    async def put(self, key: str, data: bytes) -> str:
        async with self._session.client("s3", endpoint_url=self._endpoint) as s3:
            await s3.put_object(Bucket=self._bucket, Key=key, Body=data)
        return f"s3://{self._bucket}/{key}"

    async def get(self, uri: str) -> bytes:
        bucket, _, key = uri.removeprefix("s3://").partition("/")
        async with self._session.client("s3", endpoint_url=self._endpoint) as s3:
            obj = await s3.get_object(Bucket=bucket, Key=key)
            return bytes(await obj["Body"].read())


_store: BlobStore | None = None


def initialize_storage() -> None:
    global _store
    settings = get_settings()
    _store = (
        S3BlobStore(settings)
        if settings.storage_backend == "s3"
        else LocalBlobStore(settings.local_storage_path)
    )


def get_storage() -> BlobStore:
    if _store is None:
        initialize_storage()
    assert _store is not None  # noqa: S101 - set by initialize_storage
    return _store
