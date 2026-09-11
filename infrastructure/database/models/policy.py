from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base


class PolicyRecord(Base):
    """Persistence representation of core.policy.models.VerificationPolicy.

    `ix_policies_one_active_per_tenant_assurance` is the load-bearing
    constraint (Foundation-009 discovery questions 3/6/8): a partial unique
    index over (tenant_id, assurance_level) restricted to ACTIVE rows is
    the sole final authority preventing an ambiguous active-policy state,
    including under concurrent activation -- never an application-level
    check-then-insert. It is deliberately scoped to `assurance_level` only
    for v1 applicability, not encoded as a permanent assumption that
    assurance level is the only future applicability dimension (a future
    foundation could widen this index rather than redesign the table).
    """

    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "policy_id", "version", name="uq_policies_tenant_version"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_policies_tenant_idempotency"),
        CheckConstraint(
            "(status = 'SUPERSEDED') = (superseded_at IS NOT NULL)",
            name="ck_policies_superseded_at_matches_status",
        ),
        Index("ix_policies_tenant_policy", "tenant_id", "policy_id"),
        Index(
            "ix_policies_one_active_per_tenant_assurance",
            "tenant_id",
            "assurance_level",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    assurance_level: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_requirements_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False, default=dict
    )
    conditions_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    gates_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON(none_as_null=True), nullable=False, default=list
    )
    rules_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON(none_as_null=True), nullable=False, default=list
    )
    thresholds_json: Mapped[dict[str, float]] = mapped_column(
        JSON(none_as_null=True), nullable=False, default=dict
    )
    conflict_resolution_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False, default=dict
    )
    canonical_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("policies.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
