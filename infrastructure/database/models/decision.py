from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base


class DecisionRecord(Base):
    """Persistence representation of core.decision.models.DecisionProvenance.

    `uq_decisions_tenant_session` is the load-bearing constraint (DE-003
    §14): a session gets evaluated to a durable decision exactly once,
    ever. The database, not application logic, is the final authority --
    same discipline as `ix_policies_one_active_per_tenant_assurance` and
    `ix_evidence_results_one_effective_per_type`, just an ordinary unique
    constraint here rather than a partial index, since a decision is
    permanent (never superseded, never marked ineffective) and so has no
    "which rows count" dimension those two indexes need to filter on.

    `evidence_references_json` deliberately carries no foreign key to
    `evidence_results.id` (DE-002 landmine 1 / DE-003 §12): each entry is a
    plain JSON snapshot (evidence_result_id, evidence_type, status,
    integrity_reference), structurally incapable of being a hard reference.
    A decision must survive the deletion of evidence it consumed -- an FK
    here would either block that deletion forever (the exact
    ForeignKeyViolationError the Invariant-06 Phase 6 remediation found and
    fixed, in advance) or force a cascade that fabricates historical state
    (PRV-11.35.3). `model_references_json` and `calibration_references_json`
    are plain JSON for the same reason -- neither identifies a live,
    deletable row in this schema in the first place.

    `session_id` IS a hard FK to `verification_sessions.id`, unlike
    evidence references: a session is never deleted (no tombstone
    mechanism exists for it, unlike Evidence/EvidenceResult), so there is
    no analogous "must survive deletion" requirement to protect against --
    the same reasoning `EvidenceResultRecord.session_id` already relies on.
    """

    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "session_id", name="uq_decisions_tenant_session"),
        Index("ix_decisions_tenant_session", "tenant_id", "session_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("verification_sessions.id"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_codes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    policy_id: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_references_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    model_references_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    calibration_references_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    prohibited_types_present_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    evaluation_reason: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
