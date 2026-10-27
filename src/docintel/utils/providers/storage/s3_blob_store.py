"""S3-compatible blob store (MinIO locally, AWS S3 in production)."""

import aioboto3
from botocore.exceptions import ClientError

from docintel.config import Settings
from docintel.models.errors import BlobNotFound, ProviderUnavailable


class S3BlobStore:
    def __init__(self, settings: Settings) -> None:
        self._cfg, self._session = settings, aioboto3.Session()

    async def put(self, key: str, data: bytes) -> str:
        try:
            async with self._session.client("s3", endpoint_url=self._cfg.s3_endpoint) as s3:
                await s3.put_object(Bucket=self._cfg.s3_bucket, Key=key, Body=data)
        except ClientError as exc:
            raise ProviderUnavailable(str(exc)) from exc
        return f"s3://{self._cfg.s3_bucket}/{key}"

    async def get(self, uri: str) -> bytes:
        bucket, _, key = uri.removeprefix("s3://").partition("/")
        try:
            async with self._session.client("s3", endpoint_url=self._cfg.s3_endpoint) as s3:
                obj = await s3.get_object(Bucket=bucket, Key=key)
                body: bytes = await obj["Body"].read()
                return body
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "NoSuchKey":
                raise BlobNotFound(uri) from exc
            raise ProviderUnavailable(str(exc)) from exc
