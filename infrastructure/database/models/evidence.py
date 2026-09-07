from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.evidence.enums import EvidenceSource, EvidenceType
from core.evidence.models import Evidence
from infrastructure.database.base import Base


class EvidenceRecord(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "session_id",
            "idempotency_key",
            name="uq_evidence_tenant_session_idempotency",
        ),
        Index("ix_evidence_tenant_session", "tenant_id", "session_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("verification_sessions.id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @classmethod
    def from_domain(
        cls, evidence: Evidence, idempotency_key: str | None = None
    ) -> "EvidenceRecord":
        return cls(
            id=str(evidence.id),
            session_id=str(evidence.session_id),
            tenant_id=evidence.tenant_id,
            evidence_type=evidence.evidence_type.value,
            source=evidence.source.value,
            object_key=evidence.object_key,
            checksum=evidence.checksum,
            mime_type=evidence.mime_type,
            size_bytes=evidence.size_bytes,
            metadata_json=evidence.metadata,
            idempotency_key=idempotency_key,
            created_at=evidence.created_at,
            retention_until=evidence.retention_until,
        )

    def to_domain(self) -> Evidence:
        return Evidence(
            id=UUID(self.id),
            session_id=UUID(self.session_id),
            tenant_id=self.tenant_id,
            evidence_type=EvidenceType(self.evidence_type),
            source=EvidenceSource(self.source),
            object_key=self.object_key,
            checksum=self.checksum,
            mime_type=self.mime_type,
            size_bytes=self.size_bytes,
            metadata=self.metadata_json,
            created_at=self.created_at,
            retention_until=self.retention_until,
        )
