from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class CredentialStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class CredentialRecord(BaseModel):
    """Persistable credential data; the raw secret is deliberately absent."""

    credential_id: UUID = Field(default_factory=uuid4)
    tenant_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    secret_verifier: str
    status: CredentialStatus = CredentialStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None

    def is_active(self, now: datetime | None = None) -> bool:
        current_time = now or datetime.now(UTC)
        if self.status != CredentialStatus.ACTIVE:
            return False
        if self.expires_at is not None and current_time >= self.expires_at:
            self.status = CredentialStatus.EXPIRED
            return False
        return True


class IssuedCredential(BaseModel):
    """The raw secret is returned only at issuance or rotation time."""

    credential_id: UUID
    tenant_id: str
    name: str
    secret: str
    expires_at: datetime | None
