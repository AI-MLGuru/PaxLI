from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Protocol
from uuid import UUID

from core.security.exceptions import AuthenticationError, CredentialStateError
from core.security.models import (
    CredentialRecord,
    CredentialScope,
    CredentialStatus,
    IssuedCredential,
)

_TIMING_GUARD_SECRET = "averiq-constant-time-guard-placeholder"


class SecretHasher(Protocol):
    def hash(self, secret: str) -> str: ...

    def verify(self, secret: str, verifier: str) -> bool: ...


class CredentialStore(Protocol):
    """Minimal repository contract used by the credential service."""

    async def save(self, credential: CredentialRecord) -> CredentialRecord: ...

    async def get(self, credential_id: UUID, tenant_id: str) -> CredentialRecord | None: ...

    async def get_by_id(self, credential_id: UUID) -> CredentialRecord | None: ...

    async def update(self, credential: CredentialRecord) -> CredentialRecord: ...


class CredentialService:
    def __init__(self, store: CredentialStore, hasher: SecretHasher) -> None:
        self.store = store
        self.hasher = hasher
        # Fixed-cost verifier used when no credential is found, so a lookup
        # miss and a wrong-secret match take statistically indistinguishable
        # time (SEC-7.3.6 / SEC-7.18.2).
        self._timing_guard_verifier = hasher.hash(_TIMING_GUARD_SECRET)

    async def issue(
        self,
        *,
        tenant_id: str,
        name: str,
        scope: CredentialScope = CredentialScope.OPERATIONAL,
        expires_in: timedelta | None = None,
    ) -> IssuedCredential:
        secret = f"avk_{token_urlsafe(32)}"
        expires_at = datetime.now(UTC) + expires_in if expires_in else None
        credential = CredentialRecord(
            tenant_id=tenant_id,
            name=name,
            scope=scope,
            secret_verifier=self.hasher.hash(secret),
            expires_at=expires_at,
        )
        await self.store.save(credential)
        return IssuedCredential(
            credential_id=credential.credential_id,
            tenant_id=tenant_id,
            name=name,
            scope=scope,
            secret=secret,
            expires_at=expires_at,
        )

    async def authenticate(
        self, *, credential_id: UUID, tenant_id: str, secret: str
    ) -> CredentialRecord:
        credential = await self.store.get(credential_id, tenant_id)
        return await self._verify_and_touch(credential, secret, credential_id=credential_id)

    async def authenticate_by_id(self, *, credential_id: UUID, secret: str) -> CredentialRecord:
        credential = await self.store.get_by_id(credential_id)
        return await self._verify_and_touch(credential, secret, credential_id=credential_id)

    async def _verify_and_touch(
        self, credential: CredentialRecord | None, secret: str, *, credential_id: UUID
    ) -> CredentialRecord:
        verifier = credential.secret_verifier if credential else self._timing_guard_verifier
        valid = self.hasher.verify(secret, verifier)
        if credential is None or not valid:
            raise AuthenticationError(
                credential_id=str(credential_id),
                tenant_id=credential.tenant_id if credential else None,
            )
        if not credential.is_active():
            await self.store.update(credential)
            raise AuthenticationError(
                credential_id=str(credential_id), tenant_id=credential.tenant_id
            )
        credential.last_used_at = datetime.now(UTC)
        return await self.store.update(credential)

    async def revoke(self, *, credential_id: UUID, tenant_id: str) -> None:
        credential = await self.store.get(credential_id, tenant_id)
        if credential is None:
            raise AuthenticationError(credential_id=str(credential_id), tenant_id=tenant_id)
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
        existing = await self.store.get(credential_id, tenant_id)
        if existing is None:
            raise AuthenticationError(credential_id=str(credential_id), tenant_id=tenant_id)
        await self.revoke(credential_id=credential_id, tenant_id=tenant_id)
        return await self.issue(
            tenant_id=tenant_id, name=name, scope=existing.scope, expires_in=expires_in
        )
