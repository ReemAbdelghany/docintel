"""Zero-dependency blob store on local disk, for development and demos."""

import asyncio
from pathlib import Path

from docintel.models.errors import BlobNotFound


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):  # keys come from our code, but never trust a path
            raise ValueError("storage key escapes the storage root")
        return path

    async def put(self, key: str, data: bytes) -> str:
        await asyncio.to_thread(self._write, self._path(key), data)  # keep the event loop free
        return f"local://{key}"

    async def get(self, uri: str) -> bytes:
        path = self._path(uri.removeprefix("local://"))
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            raise BlobNotFound(uri) from None

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
