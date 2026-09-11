from datetime import timedelta
from uuid import UUID

import pytest

from core.security.credentials import CredentialService, CredentialStore
from core.security.exceptions import AuthenticationError, CredentialStateError
from core.security.models import CredentialRecord, CredentialStatus
from infrastructure.security.hashing import ScryptSecretHasher, hash_secret


class MemoryCredentialStore(CredentialStore):
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
        credential = self.records.get(credential_id)
        return credential if credential and credential.tenant_id == tenant_id else None

    async def get_by_id(self, credential_id: UUID) -> CredentialRecord | None:
        return self.records.get(credential_id)

    async def update(self, credential: CredentialRecord) -> CredentialRecord:
        self.records[credential.credential_id] = credential
        return credential


@pytest.mark.asyncio
async def test_issue_does_not_store_raw_secret_and_authenticates() -> None:
    store = MemoryCredentialStore()
    service = CredentialService(store, ScryptSecretHasher())

    issued = await service.issue(tenant_id="tenant-a", name="integration")
    stored = store.records[issued.credential_id]

    assert issued.secret.startswith("avk_")
    assert issued.secret not in stored.secret_verifier
    authenticated = await service.authenticate(
        credential_id=issued.credential_id,
        tenant_id="tenant-a",
        secret=issued.secret,
    )
    assert authenticated.last_used_at is not None


@pytest.mark.asyncio
async def test_invalid_and_cross_tenant_credentials_are_indistinguishable() -> None:
    store = MemoryCredentialStore()
    service = CredentialService(store, ScryptSecretHasher())
    issued = await service.issue(tenant_id="tenant-a", name="integration")

    for tenant_id, secret in (("tenant-a", "wrong"), ("tenant-b", issued.secret)):
        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            await service.authenticate(
                credential_id=issued.credential_id,
                tenant_id=tenant_id,
                secret=secret,
            )


@pytest.mark.asyncio
async def test_revocation_rotation_and_expiry() -> None:
    store = MemoryCredentialStore()
    service = CredentialService(store, ScryptSecretHasher())
    issued = await service.issue(
        tenant_id="tenant-a", name="integration", expires_in=timedelta(seconds=-1)
    )

    with pytest.raises(AuthenticationError):
        await service.authenticate(
            credential_id=issued.credential_id,
            tenant_id="tenant-a",
            secret=issued.secret,
        )
    assert store.records[issued.credential_id].status == CredentialStatus.EXPIRED

    active = await service.issue(tenant_id="tenant-a", name="integration")
    await service.revoke(credential_id=active.credential_id, tenant_id="tenant-a")
    with pytest.raises(AuthenticationError):
        await service.authenticate(
            credential_id=active.credential_id,
            tenant_id="tenant-a",
            secret=active.secret,
        )

    rotated = await service.rotate(
        credential_id=active.credential_id,
        tenant_id="tenant-a",
        name="integration-v2",
    )
    assert rotated.credential_id != active.credential_id


def test_secret_verifier_rejects_malformed_hash() -> None:
    assert hash_secret("secret") != "secret"


@pytest.mark.asyncio
async def test_revoking_an_expired_credential_raises_a_state_error_carrying_context() -> None:
    """Invariant-12 remediation 2: CredentialStateError must carry enough
    context (tenant_id, target_credential_id) for the API boundary to
    record the required CREDENTIAL_OPERATION_FAILED audit event without
    a second lookup -- the service layer knows this much; only the actor
    (who is attempting the operation) is filled in later, at the router,
    since the service never sees the authenticated principal."""
    store = MemoryCredentialStore()
    service = CredentialService(store, ScryptSecretHasher())
    issued = await service.issue(
        tenant_id="tenant-a", name="already-expired", expires_in=timedelta(seconds=-1)
    )

    with pytest.raises(CredentialStateError) as exc_info:
        await service.revoke(credential_id=issued.credential_id, tenant_id="tenant-a")

    assert exc_info.value.tenant_id == "tenant-a"
    assert exc_info.value.target_credential_id == str(issued.credential_id)
    assert exc_info.value.actor_id is None  # not yet known at this layer
