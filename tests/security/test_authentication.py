from uuid import UUID

import pytest

from apps.api.averiq_api.dependencies import get_principal
from apps.api.averiq_api.routers.verification_sessions import tenant_from_principal
from core.security.authentication import authenticate_bearer
from core.security.credentials import CredentialService
from core.security.exceptions import AuthenticationError
from core.security.models import CredentialRecord
from infrastructure.security.hashing import ScryptSecretHasher


class MemoryCredentialStore:
    def __init__(self) -> None:
        self.records: dict[UUID, CredentialRecord] = {}

    async def save(self, credential: CredentialRecord) -> CredentialRecord:
        self.records[credential.credential_id] = credential
        return credential

    async def get(self, credential_id: UUID, tenant_id: str) -> CredentialRecord | None:
        record = self.records.get(credential_id)
        return record if record and record.tenant_id == tenant_id else None

    async def get_by_id(self, credential_id: UUID) -> CredentialRecord | None:
        return self.records.get(credential_id)

    async def update(self, credential: CredentialRecord) -> CredentialRecord:
        self.records[credential.credential_id] = credential
        return credential


@pytest.mark.asyncio
async def test_bearer_authentication_derives_tenant_from_credential() -> None:
    store = MemoryCredentialStore()
    service = CredentialService(store, ScryptSecretHasher())
    issued = await service.issue(tenant_id="tenant-a", name="client")

    principal = await authenticate_bearer(f"Bearer {issued.credential_id}.{issued.secret}", service)

    assert principal.tenant_id == "tenant-a"
    assert principal.credential_id == issued.credential_id


@pytest.mark.asyncio
async def test_malformed_or_cross_tenant_bearer_tokens_are_generic_failures() -> None:
    store = MemoryCredentialStore()
    service = CredentialService(store, ScryptSecretHasher())
    issued = await service.issue(tenant_id="tenant-a", name="client")

    for authorization in (
        None,
        "Basic credentials",
        "Bearer malformed",
        f"Bearer {issued.credential_id}.wrong",
    ):
        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            await authenticate_bearer(authorization, service)


@pytest.mark.asyncio
async def test_principal_dependency_uses_authenticated_tenant_not_header_value() -> None:
    store = MemoryCredentialStore()
    service = CredentialService(store, ScryptSecretHasher())
    issued = await service.issue(tenant_id="tenant-a", name="client")

    principal = await get_principal(f"Bearer {issued.credential_id}.{issued.secret}", service)

    assert principal.tenant_id == "tenant-a"
    assert tenant_from_principal(principal=principal) == "tenant-a"


@pytest.mark.asyncio
async def test_get_principal_rejects_missing_or_invalid_bearer_tokens() -> None:
    store = MemoryCredentialStore()
    service = CredentialService(store, ScryptSecretHasher())
    issued = await service.issue(tenant_id="tenant-a", name="client")

    for authorization in (
        None,
        "Basic credentials",
        "Bearer malformed",
        f"Bearer {issued.credential_id}.wrong",
    ):
        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            await get_principal(authorization, service)
