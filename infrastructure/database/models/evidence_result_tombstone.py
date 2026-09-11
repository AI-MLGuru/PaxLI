from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from core.deletion.enums import DeletionBasis
from core.evidence_result.models import EvidenceResultTombstone
from infrastructure.database.base import Base


class EvidenceResultTombstoneRecord(Base):
    """core.evidence_result.models.EvidenceResultTombstone, persisted.

    Same non-FK rationale as EvidenceTombstoneRecord.evidence_id: by the
    time Phase-2 reconciliation completes, the referenced `evidence_results`
    row has been physically deleted, so `evidence_result_id` cannot be a
    foreign key. The primary key on `evidence_result_id` alone enforces
    "one tombstone per deleted resource".
    """

    __tablename__ = "evidence_result_tombstones"
    __table_args__ = (
        CheckConstraint(
            "deletion_basis IN ("
            "'TENANT_REQUEST', 'DATA_SUBJECT_REQUEST', 'RETENTION_EXPIRY', "
            "'LEGAL_REQUIREMENT', 'OTHER_AUTHORIZED_BASIS')",
            name="ck_evidence_result_tombstones_deletion_basis",
        ),
        CheckConstraint(
            "executed_at IS NULL OR executed_at >= requested_at",
            name="ck_evidence_result_tombstones_executed_after_requested",
        ),
        Index("ix_evidence_result_tombstones_tenant", "tenant_id"),
    )

    evidence_result_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("verification_sessions.id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    deletion_basis: Mapped[str] = mapped_column(String(32), nullable=False)
    basis_reference: Mapped[str | None] = mapped_column(String(512))
    authorized_by: Mapped[str] = mapped_column(String(256), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_integrity_reference: Mapped[str] = mapped_column(String(128), nullable=False)

    @classmethod
    def from_domain(
        cls, tombstone: EvidenceResultTombstone
    ) -> "EvidenceResultTombstoneRecord":
        return cls(
            evidence_result_id=str(tombstone.evidence_result_id),
            session_id=str(tombstone.session_id),
            tenant_id=tombstone.tenant_id,
            deletion_basis=tombstone.deletion_basis.value,
            basis_reference=tombstone.basis_reference,
            authorized_by=tombstone.authorized_by,
            requested_at=tombstone.requested_at,
            executed_at=tombstone.executed_at,
            evidence_integrity_reference=tombstone.evidence_integrity_reference,
        )

    def to_domain(self) -> EvidenceResultTombstone:
        return EvidenceResultTombstone(
            evidence_result_id=UUID(self.evidence_result_id),
            session_id=UUID(self.session_id),
            tenant_id=self.tenant_id,
            deletion_basis=DeletionBasis(self.deletion_basis),
            basis_reference=self.basis_reference,
            authorized_by=self.authorized_by,
            requested_at=self.requested_at,
            executed_at=self.executed_at,
            evidence_integrity_reference=self.evidence_integrity_reference,
        )
