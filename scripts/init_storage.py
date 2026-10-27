"""Create the S3/MinIO bucket named in settings. Run once: uv run python scripts/init_storage.py"""

import asyncio

import aioboto3
from botocore.exceptions import ClientError

from docintel.config import Settings


async def main() -> None:
    settings = Settings()
    async with aioboto3.Session().client("s3", endpoint_url=settings.s3_endpoint) as s3:
        try:
            await s3.head_bucket(Bucket=settings.s3_bucket)
            print(f"bucket {settings.s3_bucket} already exists")
        except ClientError:
            await s3.create_bucket(Bucket=settings.s3_bucket)
            print(f"created bucket {settings.s3_bucket}")


if __name__ == "__main__":
    asyncio.run(main())
