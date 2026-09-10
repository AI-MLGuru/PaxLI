from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from core.security.models import CredentialRecord, CredentialScope, CredentialStatus
from infrastructure.database.base import Base


class CredentialRecordModel(Base):
    __tablename__ = "credentials"
    __table_args__ = (Index("ix_credentials_tenant_id", "tenant_id"),)

    credential_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    secret_verifier: Mapped[str] = mapped_column(String(512), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CredentialScope.OPERATIONAL.value
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @classmethod
    def from_domain(cls, credential: CredentialRecord) -> "CredentialRecordModel":
        return cls(
            credential_id=str(credential.credential_id),
            tenant_id=credential.tenant_id,
            name=credential.name,
            secret_verifier=credential.secret_verifier,
            scope=credential.scope.value,
            status=credential.status.value,
            created_at=credential.created_at,
            expires_at=credential.expires_at,
            revoked_at=credential.revoked_at,
            last_used_at=credential.last_used_at,
        )

    def to_domain(self) -> CredentialRecord:
        return CredentialRecord(
            credential_id=UUID(self.credential_id),
            tenant_id=self.tenant_id,
            name=self.name,
            secret_verifier=self.secret_verifier,
            scope=CredentialScope(self.scope),
            status=CredentialStatus(self.status),
            created_at=self.created_at,
            expires_at=self.expires_at,
            revoked_at=self.revoked_at,
            last_used_at=self.last_used_at,
        )

    def update_from_domain(self, credential: CredentialRecord) -> None:
        self.status = credential.status.value
        self.expires_at = credential.expires_at
        self.revoked_at = credential.revoked_at
        self.last_used_at = credential.last_used_at
