from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Protocol
from uuid import UUID

from core.security.exceptions import (
    AuthenticationError,
    CredentialStateError,
    IdempotentReplayWithoutSecretError,
)
from core.security.models import (
    CredentialRecord,
    CredentialScope,
    CredentialStatus,
    IssuedCredential,
)

_TIMING_GUARD_SECRET = "paxli-constant-time-guard-placeholder"
_ISSUE_IDEMPOTENCY_OPERATION = "credential_issue"
_ROTATE_IDEMPOTENCY_OPERATION = "credential_rotate"


class SecretHasher(Protocol):
    def hash(self, secret: str) -> str: ...

    def verify(self, secret: str, verifier: str) -> bool: ...


class CredentialStore(Protocol):
    """Minimal repository contract used by the credential service."""

    async def save(
        self, credential: CredentialRecord, idempotency_key: str | None = None
    ) -> CredentialRecord: ...

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> CredentialRecord | None:
        """`idempotency_key` is the composed, operation-scoped key (e.g.
        "credential_issue:<caller-key>") -- see CredentialService for
        composition (Invariant-12 remediation review: a reused raw key
        must never collide between issue and rotate)."""
        ...

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
        idempotency_key: str | None = None,
    ) -> IssuedCredential:
        """Raises IdempotentReplayWithoutSecretError if `idempotency_key`
        matches an already-completed issuance -- the stored record holds
        only a one-way secret_verifier hash, so a replay cannot return the
        original secret (SEC-7.9.9). Returning "success" without it would
        be worse than an error: the caller could not tell it was missing
        (Invariant-12 remediation, explicit decision)."""
        composed_key = (
            f"{_ISSUE_IDEMPOTENCY_OPERATION}:{idempotency_key}"
            if idempotency_key is not None
            else None
        )
        if composed_key is not None:
            existing = await self.store.get_by_idempotency_key(tenant_id, composed_key)
            if existing is not None:
                raise IdempotentReplayWithoutSecretError(credential_id=str(existing.credential_id))
        return await self._issue_new_credential(
            tenant_id=tenant_id,
            name=name,
            scope=scope,
            expires_in=expires_in,
            composed_idempotency_key=composed_key,
        )

    async def _issue_new_credential(
        self,
        *,
        tenant_id: str,
        name: str,
        scope: CredentialScope,
        expires_in: timedelta | None,
        composed_idempotency_key: str | None,
    ) -> IssuedCredential:
        """The actual creation, shared by issue() and rotate() -- each of
        those does its own operation-scoped idempotency check (different
        composed-key prefixes, so a reused raw key can never collide
        between issue and rotate) before calling this."""
        secret = f"avk_{token_urlsafe(32)}"
        expires_at = datetime.now(UTC) + expires_in if expires_in else None
        credential = CredentialRecord(
            tenant_id=tenant_id,
            name=name,
            scope=scope,
            secret_verifier=self.hasher.hash(secret),
            expires_at=expires_at,
        )
        await self.store.save(credential, composed_idempotency_key)
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
            raise CredentialStateError(
                "Credential is no longer active",
                tenant_id=tenant_id,
                target_credential_id=str(credential_id),
            )
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
        idempotency_key: str | None = None,
    ) -> IssuedCredential:
        """Raises IdempotentReplayWithoutSecretError on a same-key replay,
        same reasoning as issue() -- the new secret from the original
        rotation cannot be recovered (SEC-7.9.9)."""
        composed_key = (
            f"{_ROTATE_IDEMPOTENCY_OPERATION}:{idempotency_key}"
            if idempotency_key is not None
            else None
        )
        if composed_key is not None:
            existing_replay = await self.store.get_by_idempotency_key(tenant_id, composed_key)
            if existing_replay is not None:
                raise IdempotentReplayWithoutSecretError(
                    credential_id=str(existing_replay.credential_id)
                )

        existing = await self.store.get(credential_id, tenant_id)
        if existing is None:
            raise AuthenticationError(credential_id=str(credential_id), tenant_id=tenant_id)
        await self.revoke(credential_id=credential_id, tenant_id=tenant_id)
        return await self._issue_new_credential(
            tenant_id=tenant_id,
            name=name,
            scope=existing.scope,
            expires_in=expires_in,
            composed_idempotency_key=composed_key,
        )
