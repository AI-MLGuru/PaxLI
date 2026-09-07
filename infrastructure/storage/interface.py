from typing import Protocol


class ObjectStorage(Protocol):
    async def put(self, object_key: str, content: bytes, content_type: str) -> None: ...

    async def delete(self, object_key: str) -> None: ...
