from typing import Protocol


class KeyProviderError(RuntimeError):
    """Raised when an encryption/decryption operation cannot be completed."""


class KeyProvider(Protocol):
    """Operation-based cryptographic boundary.

    Application code performs encrypt/decrypt/rotate operations through this
    interface and never receives raw master key material, so implementations
    can be backed by a local key, a Vault-like secrets engine, or a managed
    KMS/HSM without changing call sites.
    """

    async def encrypt(self, plaintext: bytes, key_id: str) -> bytes: ...

    async def decrypt(self, ciphertext: bytes, key_id: str) -> bytes: ...

    async def rotate_key(self, key_id: str) -> str: ...
