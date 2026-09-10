"""Requirement traceability: REL-10.9.5, REL-10.20 (no duplicate/corrupt
authoritative state from a retried write).

Proves the specific claim in infrastructure/reliability/minio_policies.py:
retrying PUT is safe not because "S3 PUT is generally idempotent" but
because of three properties that hold together here -- content-addressed
keys, full-replace semantics, and plaintext-checksum verification
independent of which nonce produced the stored ciphertext.
"""

from infrastructure.security.local_key_provider import LocalAesGcmKeyProvider
from infrastructure.storage.encrypted import EncryptedObjectStorage
from tests.conftest import FakeObjectStorage


async def test_retried_put_overwrites_with_different_ciphertext_but_identical_plaintext() -> None:
    storage = FakeObjectStorage()
    key_provider = LocalAesGcmKeyProvider({"k": b"0" * 32})
    encrypted_storage = EncryptedObjectStorage(storage, key_provider, "k")
    plaintext = b"CANARY_EVIDENCE_BYTES_UNCHANGED_ACROSS_RETRY"
    key = "tenant/session/selfie/checksum"

    # First "attempt": the client's request context believes this may have
    # failed (e.g. the response was lost), so it retries with identical
    # logical input -- same key, same plaintext.
    await encrypted_storage.put(key, plaintext, "image/jpeg")
    first_ciphertext = storage.blobs[key]

    await encrypted_storage.put(key, plaintext, "image/jpeg")
    second_ciphertext = storage.blobs[key]

    # Different bytes stored (fresh AES-GCM nonce each call) -- this is
    # expected and correct, not a bug.
    assert first_ciphertext != second_ciphertext

    # But the final, retrievable state is exactly the original plaintext,
    # regardless of which PUT attempt's bytes ended up persisted.
    recovered = await encrypted_storage.get(key)
    assert recovered == plaintext

    # Only one object exists at the key -- PUT is a full replace, not an
    # append; a retry cannot create a duplicate or corrupt entry.
    assert len(storage.blobs) == 1


async def test_retried_put_with_different_plaintext_at_same_key_is_not_silently_merged() -> None:
    """A retry must carry identical logical input; this test documents (not
    endorses) what happens if it doesn't, since object-key determinism
    depends on the checksum matching the content."""
    storage = FakeObjectStorage()
    key_provider = LocalAesGcmKeyProvider({"k": b"0" * 32})
    encrypted_storage = EncryptedObjectStorage(storage, key_provider, "k")
    key = "tenant/session/selfie/checksum"

    await encrypted_storage.put(key, b"CANARY_FIRST", "image/jpeg")
    await encrypted_storage.put(key, b"CANARY_SECOND", "image/jpeg")

    recovered = await encrypted_storage.get(key)
    assert recovered == b"CANARY_SECOND"  # last write wins, no merge/corruption
