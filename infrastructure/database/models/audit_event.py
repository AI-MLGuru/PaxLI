from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.audit.enums import AuditActorType, AuditEventType, AuditStatus
from core.audit.models import AuditEvent
from infrastructure.database.base import Base


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "session_id",
            "dedupe_key",
            name="uq_audit_tenant_session_dedupe",
        ),
        Index("ix_audit_tenant_session_occurred", "tenant_id", "session_id", "occurred_at"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("verification_sessions.id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(256))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(256))
    correlation_id: Mapped[str | None] = mapped_column(String(256))
    component: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(256))

    @classmethod
    def from_domain(cls, event: AuditEvent, dedupe_key: str | None = None) -> "AuditEventRecord":
        return cls(
            event_id=str(event.event_id),
            tenant_id=event.tenant_id,
            session_id=str(event.session_id) if event.session_id else None,
            event_type=event.event_type.value,
            actor_type=event.actor_type.value,
            actor_id=event.actor_id,
            occurred_at=event.occurred_at,
            request_id=event.request_id,
            correlation_id=event.correlation_id,
            component=event.component,
            action=event.action,
            status=event.status.value,
            reason_code=event.reason_code,
            metadata_json=event.metadata,
            dedupe_key=dedupe_key,
        )

    def to_domain(self) -> AuditEvent:
        return AuditEvent(
            event_id=UUID(self.event_id),
            tenant_id=self.tenant_id,
            session_id=UUID(self.session_id) if self.session_id else None,
            event_type=AuditEventType(self.event_type),
            actor_type=AuditActorType(self.actor_type),
            actor_id=self.actor_id,
            occurred_at=self.occurred_at,
            request_id=self.request_id,
            correlation_id=self.correlation_id,
            component=self.component,
            action=self.action,
            status=AuditStatus(self.status),
            reason_code=self.reason_code,
            metadata=self.metadata_json,
        )