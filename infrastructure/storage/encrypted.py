from core.security.keys import KeyProvider
from infrastructure.storage.interface import ObjectStorage


class EncryptedObjectStorage:
    """Encrypts evidence bytes before they reach an inner `ObjectStorage`.

    The inner storage adapter (e.g. MinIO) never sees plaintext and has no
    awareness of Averiq's cryptographic policy; encryption is applied at this
    boundary, keyed by an opaque `key_id` resolved through `KeyProvider`.
    """

    def __init__(self, storage: ObjectStorage, key_provider: KeyProvider, key_id: str) -> None:
        self._storage = storage
        self._key_provider = key_provider
        self._key_id = key_id

    async def put(self, object_key: str, content: bytes, content_type: str) -> None:
        ciphertext = await self._key_provider.encrypt(content, self._key_id)
        await self._storage.put(object_key, ciphertext, content_type)

    async def get(self, object_key: str) -> bytes:
        ciphertext = await self._storage.get(object_key)
        return await self._key_provider.decrypt(ciphertext, self._key_id)

    async def delete(self, object_key: str) -> None:
        await self._storage.delete(object_key)
