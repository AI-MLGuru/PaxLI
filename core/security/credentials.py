from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Protocol
from uuid import UUID

from core.security.exceptions import AuthenticationError, CredentialStateError
from core.security.models import CredentialRecord, CredentialStatus, IssuedCredential


class SecretHasher(Protocol):
    def hash(self, secret: str) -> str: ...

    def verify(self, secret: str, verifier: str) -> bool: ...


class CredentialStore(Protocol):
    """Minimal repository contract used by the credential service."""

    async def save(self, credential: CredentialRecord) -> CredentialRecord: ...

    async def get(self, credential_id: UUID, tenant_id: str) -> CredentialRecord | None: ...

    async def update(self, credential: CredentialRecord) -> CredentialRecord: ...


class CredentialService:
    def __init__(self, store: CredentialStore, hasher: SecretHasher) -> None:
        self.store = store
        self.hasher = hasher

    async def issue(
        self,
        *,
        tenant_id: str,
        name: str,
        expires_in: timedelta | None = None,
    ) -> IssuedCredential:
        secret = f"avk_{token_urlsafe(32)}"
        expires_at = datetime.now(UTC) + expires_in if expires_in else None
        credential = CredentialRecord(
            tenant_id=tenant_id,
            name=name,
            secret_verifier=self.hasher.hash(secret),
            expires_at=expires_at,
        )
        await self.store.save(credential)
        return IssuedCredential(
            credential_id=credential.credential_id,
            tenant_id=tenant_id,
            name=name,
            secret=secret,
            expires_at=expires_at,
        )

    async def authenticate(
        self, *, credential_id: UUID, tenant_id: str, secret: str
    ) -> CredentialRecord:
        credential = await self.store.get(credential_id, tenant_id)
        if credential is None or not self.hasher.verify(secret, credential.secret_verifier):
            raise AuthenticationError("Invalid credentials")
        if not credential.is_active():
            await self.store.update(credential)
            raise AuthenticationError("Invalid credentials")
        credential.last_used_at = datetime.now(UTC)
        return await self.store.update(credential)

    async def revoke(self, *, credential_id: UUID, tenant_id: str) -> None:
        credential = await self.store.get(credential_id, tenant_id)
        if credential is None:
            raise AuthenticationError("Invalid credentials")
        if credential.status == CredentialStatus.REVOKED:
            return
        if not credential.is_active():
            raise CredentialStateError("Credential is no longer active")
        credential.status = CredentialStatus.REVOKED
        credential.revoked_at = datetime.now(UTC)
        await self.store.update(credential)

    async def rotate(
        self,
        *,
        credential_id: UUID,
        tenant_id: str,
        name: str,
        expires_in: timedelta | None = None,
    ) -> IssuedCredential:
        await self.revoke(credential_id=credential_id, tenant_id=tenant_id)
        return await self.issue(tenant_id=tenant_id, name=name, expires_in=expires_in)