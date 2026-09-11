import asyncio
from io import BytesIO
from typing import Any

from apps.api.paxli_api.config import Settings
from infrastructure.reliability.minio_policies import guarded_delete, guarded_get, guarded_put


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
        async def _do_put() -> None:
            await self.ensure_bucket()
            await asyncio.to_thread(
                self.client.put_object,
                self.bucket,
                object_key,
                BytesIO(content),
                len(content),
                content_type,
            )

        await guarded_put(_do_put)

    async def get(self, object_key: str) -> bytes:
        async def _do_get() -> bytes:
            response = await asyncio.to_thread(self.client.get_object, self.bucket, object_key)
            try:
                return await asyncio.to_thread(response.read)
            finally:
                response.close()
                response.release_conn()

        return await guarded_get(_do_get)

    async def delete(self, object_key: str) -> None:
        async def _do_delete() -> None:
            try:
                await asyncio.to_thread(self.client.remove_object, self.bucket, object_key)
            except Exception as exception:
                from minio.error import S3Error

                if not isinstance(exception, S3Error):
                    raise

        await guarded_delete(_do_delete)
