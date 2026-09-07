import asyncio
from io import BytesIO
from typing import Any

from apps.api.averiq_api.config import Settings


class MinioObjectStorage:
    def __init__(self, settings: Settings) -> None:
        from minio import Minio

        self.bucket = settings.storage_bucket
        self.client: Any = Minio(
            settings.storage_endpoint,
            access_key=settings.storage_access_key,
            secret_key=settings.storage_secret_key,
            secure=settings.storage_secure,
        )

    async def ensure_bucket(self) -> None:
        exists = await asyncio.to_thread(self.client.bucket_exists, self.bucket)
        if not exists:
            await asyncio.to_thread(self.client.make_bucket, self.bucket)

    async def put(self, object_key: str, content: bytes, content_type: str) -> None:
        await self.ensure_bucket()
        await asyncio.to_thread(
            self.client.put_object,
            self.bucket,
            object_key,
            BytesIO(content),
            len(content),
            content_type,
        )

    async def delete(self, object_key: str) -> None:
        try:
            await asyncio.to_thread(self.client.remove_object, self.bucket, object_key)
        except Exception as exception:
            from minio.error import S3Error

            if not isinstance(exception, S3Error):
                raise
            pass
