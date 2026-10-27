"""Blob storage adapters, selected by settings."""

from docintel.config import Settings
from docintel.shared.ports import BlobStore
from docintel.utils.providers.storage.local_blob_store import LocalBlobStore
from docintel.utils.providers.storage.s3_blob_store import S3BlobStore


def make_blob_store(settings: Settings) -> BlobStore:
    """Build the store named by settings.storage_backend."""
    match settings.storage_backend:
        case "local":
            return LocalBlobStore(settings.local_storage_path)
        case "s3":
            return S3BlobStore(settings)
