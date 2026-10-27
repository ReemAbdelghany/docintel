from pathlib import Path

import pytest

from docintel.models.errors import BlobNotFound
from docintel.shared.ports import BlobStore
from docintel.utils.providers.storage.local_blob_store import LocalBlobStore
from tests.unit_tests.fakes import InMemoryBlobStore


@pytest.fixture(params=["memory", "local"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> BlobStore:
    if request.param == "memory":
        return InMemoryBlobStore()
    return LocalBlobStore(tmp_path)


async def test_round_trip(store: BlobStore) -> None:
    uri = await store.put("cases/c1/doc.pdf", b"abc")

    assert await store.get(uri) == b"abc"


async def test_missing_key_raises_blob_not_found(store: BlobStore) -> None:
    uri = await store.put("x", b"1")

    with pytest.raises(BlobNotFound):
        await store.get(uri + "-missing")


async def test_local_store_refuses_keys_that_escape_the_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        await LocalBlobStore(tmp_path).put("../outside", b"x")
