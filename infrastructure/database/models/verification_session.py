from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.verification.enums import AssuranceLevel, VerificationStatus
from core.verification.models import VerificationSession
from infrastructure.database.base import Base


class VerificationSessionRecord(Base):
    __tablename__ = "verification_sessions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_session_tenant_idempotency"),
        Index("ix_session_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(256))
    idempotency_key: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    assurance_level: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @classmethod
    def from_domain(
        cls, session: VerificationSession, idempotency_key: str | None = None
    ) -> "VerificationSessionRecord":
        return cls(
            id=str(session.id),
            tenant_id=session.tenant_id,
            external_reference=session.external_reference,
            idempotency_key=idempotency_key,
            status=session.status.value,
            assurance_level=session.assurance_level.value,
            created_at=session.created_at,
            expires_at=session.expires_at,
            completed_at=session.completed_at,
        )

    def to_domain(self) -> VerificationSession:
        return VerificationSession(
            id=UUID(self.id),
            tenant_id=self.tenant_id,
            external_reference=self.external_reference,
            status=VerificationStatus(self.status),
            assurance_level=AssuranceLevel(self.assurance_level),
            created_at=self.created_at,
            expires_at=self.expires_at,
            completed_at=self.completed_at,
        )

    def update_from_domain(self, session: VerificationSession) -> None:
        self.status = session.status.value
        self.expires_at = session.expires_at
        self.completed_at = session.completed_at
