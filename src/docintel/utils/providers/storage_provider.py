"""Blob storage abstraction with local and S3-compatible backends.

This module provides a unified interface for blob storage operations, supporting
two backends:
- Local filesystem storage (default) - stores files on disk with local:// URIs
- S3-compatible storage (MinIO, AWS S3) - stores objects in S3 buckets with s3:// URIs

The storage backend is selected via the `storage_backend` setting. Both backends
implement the same `BlobStore` protocol, allowing the rest of the application
to remain storage-agnostic.

The store is initialized once at startup and accessed via `get_storage()`.
"""

import asyncio
from pathlib import Path
from typing import Protocol

import aioboto3

from docintel.config import Settings, get_settings


class BlobStore(Protocol):
    """Protocol defining the blob storage interface.

    All storage backends must implement these two methods for storing and
    retrieving binary data.
    """

    async def put(self, key: str, data: bytes) -> str:
        """Store bytes and return a URI that says where they live.

        Args:
            key: Storage key/path for the object.
            data: Binary data to store.

        Returns:
            str: URI referencing the stored object (e.g., "local://path/to/file"
                or "s3://bucket/key").
        """
        ...

    async def get(self, uri: str) -> bytes:
        """Retrieve bytes from a storage URI.

        Args:
            uri: URI returned by a previous put() call.

        Returns:
            bytes: The stored binary data.

        Raises:
            FileNotFoundError: If the object doesn't exist.
            ValueError: If the URI format is invalid.
        """
        ...


class LocalBlobStore:
    """Local filesystem blob storage implementation.

    Stores files under a configured root directory. All paths are resolved
    and validated to prevent directory traversal attacks.
    """

    def __init__(self, root: Path) -> None:
        """Initialize local storage with a root directory.

        Args:
            root: Root directory for file storage. Will be resolved to absolute path.
        """
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        """Resolve a storage key to a filesystem path with security validation.

        Args:
            key: Storage key (relative path).

        Returns:
            Path: Resolved absolute path within the storage root.

        Raises:
            ValueError: If the resolved path escapes the storage root directory.
        """
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError("storage key escapes the storage root")
        return path

    async def put(self, key: str, data: bytes) -> str:
        """Store bytes to local filesystem.

        Creates parent directories as needed. Runs file I/O in a thread pool
        to avoid blocking the event loop.

        Args:
            key: Storage key (relative path).
            data: Binary data to store.

        Returns:
            str: local:// URI referencing the stored file.
        """
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        return f"local://{key}"

    async def get(self, uri: str) -> bytes:
        """Retrieve bytes from local filesystem.

        Args:
            uri: local:// URI returned by put().

        Returns:
            bytes: The stored binary data.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the URI doesn't have the local:// prefix.
        """
        return await asyncio.to_thread(self._path(uri.removeprefix("local://")).read_bytes)


class S3BlobStore:
    """S3-compatible blob storage implementation.

    Uses aioboto3 for async S3 operations. Compatible with AWS S3, MinIO,
    and other S3-compatible object stores.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize S3 storage with settings.

        Args:
            settings: Application settings containing S3 endpoint and bucket name.
        """
        self._endpoint, self._bucket = settings.s3_endpoint, settings.s3_bucket
        self._session = aioboto3.Session()

    async def put(self, key: str, data: bytes) -> str:
        """Store bytes to S3-compatible object store.

        Args:
            key: Object key in the bucket.
            data: Binary data to store.

        Returns:
            str: s3:// URI referencing the stored object.
        """
        async with self._session.client("s3", endpoint_url=self._endpoint) as s3:
            await s3.put_object(Bucket=self._bucket, Key=key, Body=data)
        return f"s3://{self._bucket}/{key}"

    async def get(self, uri: str) -> bytes:
        """Retrieve bytes from S3-compatible object store.

        Args:
            uri: s3:// URI returned by put().

        Returns:
            bytes: The stored binary data.

        Raises:
            ClientError: If the object doesn't exist or access is denied.
            ValueError: If the URI format is invalid.
        """
        bucket, _, key = uri.removeprefix("s3://").partition("/")
        async with self._session.client("s3", endpoint_url=self._endpoint) as s3:
            obj = await s3.get_object(Bucket=bucket, Key=key)
            return bytes(await obj["Body"].read())


_store: BlobStore | None = None


def initialize_storage() -> None:
    """Initialize the global storage backend based on settings.

    Creates either an S3BlobStore or LocalBlobStore depending on the
    `storage_backend` setting. This function is idempotent and called
    automatically by `get_storage()` on first use.

    The S3 backend is used when `storage_backend == "s3"`, otherwise
    the local filesystem backend is used.
    """
    global _store
    settings = get_settings()
    _store = (
        S3BlobStore(settings)
        if settings.storage_backend == "s3"
        else LocalBlobStore(settings.local_storage_path)
    )


def get_storage() -> BlobStore:
    """Get the global storage backend, initializing if necessary.

    Returns the configured storage backend (local or S3). Lazily initializes
    the storage on first call.

    Returns:
        BlobStore: The configured storage backend implementation.
    """
    if _store is None:
        initialize_storage()
    assert _store is not None  # noqa: S101 - set by initialize_storage
    return _store
