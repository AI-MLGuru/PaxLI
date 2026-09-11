from uuid import UUID, uuid4

import pytest

from core.security.credentials import CredentialService
from core.security.exceptions import AuthenticationError
from core.security.models import CredentialRecord
from infrastructure.security.hashing import ScryptSecretHasher


class SpyHasher:
    """Wraps the real hasher and counts verify() calls, to prove the unknown-id
    and wrong-secret paths do the same cryptographic work (SEC-7.3.6 / SEC-7.18.2)."""

    def __init__(self) -> None:
        self._inner = ScryptSecretHasher()
        self.verify_calls = 0

    def hash(self, secret: str) -> str:
        return self._inner.hash(secret)

    def verify(self, secret: str, verifier: str) -> bool:
        self.verify_calls += 1
        return self._inner.verify(secret, verifier)


class MemoryCredentialStore:
    def __init__(self) -> None:
        self.records: dict[UUID, CredentialRecord] = {}
        self.idempotency_keys: dict[tuple[str, str], UUID] = {}

    async def save(
        self, credential: CredentialRecord, idempotency_key: str | None = None
    ) -> CredentialRecord:
        self.records[credential.credential_id] = credential
        if idempotency_key is not None:
            self.idempotency_keys[(credential.tenant_id, idempotency_key)] = (
                credential.credential_id
            )
        return credential

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> CredentialRecord | None:
        credential_id = self.idempotency_keys.get((tenant_id, idempotency_key))
        return self.records.get(credential_id) if credential_id is not None else None

    async def get(self, credential_id: UUID, tenant_id: str) -> CredentialRecord | None:
        record = self.records.get(credential_id)
        return record if record and record.tenant_id == tenant_id else None

    async def get_by_id(self, credential_id: UUID) -> CredentialRecord | None:
        return self.records.get(credential_id)

    async def update(self, credential: CredentialRecord) -> CredentialRecord:
        self.records[credential.credential_id] = credential
        return credential


@pytest.mark.asyncio
async def test_unknown_credential_performs_a_verify_call_like_a_real_one() -> None:
    store = MemoryCredentialStore()
    hasher = SpyHasher()
    service = CredentialService(store, hasher)
    issued = await service.issue(tenant_id="tenant-a", name="client")

    hasher.verify_calls = 0
    with pytest.raises(AuthenticationError):
        await service.authenticate(credential_id=uuid4(), tenant_id="tenant-a", secret="wrong")
    calls_for_unknown_id = hasher.verify_calls

    hasher.verify_calls = 0
    with pytest.raises(AuthenticationError):
        await service.authenticate(
            credential_id=issued.credential_id, tenant_id="tenant-a", secret="wrong"
        )
    calls_for_wrong_secret = hasher.verify_calls

    assert calls_for_unknown_id == calls_for_wrong_secret == 1
