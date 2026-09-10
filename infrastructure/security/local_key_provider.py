import base64
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.security.keys import KeyProviderError

_NONCE_BYTES = 12


class LocalAesGcmKeyProvider:
    """Local AES-256-GCM `KeyProvider`.

    Keys never leave this module: callers only ever pass plaintext/ciphertext
    and a `key_id`. A production deployment swaps this for a Vault/KMS/HSM
    backed implementation of the same `KeyProvider` protocol without any
    change to call sites.
    """

    def __init__(self, keys: dict[str, bytes]) -> None:
        if not keys:
            raise ValueError("At least one key must be configured")
        self._keys = dict(keys)

    async def encrypt(self, plaintext: bytes, key_id: str) -> bytes:
        key = self._require_key(key_id)
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, key_id.encode("utf-8"))
        return nonce + ciphertext

    async def decrypt(self, ciphertext: bytes, key_id: str) -> bytes:
        key = self._require_key(key_id)
        if len(ciphertext) < _NONCE_BYTES:
            raise KeyProviderError("Ciphertext is malformed")
        nonce, body = ciphertext[:_NONCE_BYTES], ciphertext[_NONCE_BYTES:]
        try:
            return AESGCM(key).decrypt(nonce, body, key_id.encode("utf-8"))
        except Exception as exception:
            raise KeyProviderError("Decryption failed") from exception

    async def rotate_key(self, key_id: str) -> str:
        base, _, version = key_id.rpartition("-v")
        next_version = int(version) + 1 if version.isdigit() else 2
        new_key_id = f"{base or key_id}-v{next_version}"
        self._keys[new_key_id] = AESGCM.generate_key(256)
        return new_key_id

    def _require_key(self, key_id: str) -> bytes:
        key = self._keys.get(key_id)
        if key is None:
            raise KeyProviderError(f"Unknown key_id: {key_id}")
        return key


def _load_key(encoded_key: str | None) -> bytes:
    if not encoded_key:
        return AESGCM.generate_key(256)
    return base64.b64decode(encoded_key)


@lru_cache
def get_local_key_provider(*, key_id: str, encoded_key: str | None) -> LocalAesGcmKeyProvider:
    return LocalAesGcmKeyProvider({key_id: _load_key(encoded_key)})
