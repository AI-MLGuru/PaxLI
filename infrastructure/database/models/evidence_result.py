from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base


class EvidenceResultRecord(Base):
    """Persistence representation of core.evidence_result.models.EvidenceResult.

    `result_json` / `result_ciphertext` are mutually exclusive by DB-level
    CHECK constraint, not application code alone (both may be NULL, meaning
    no payload; exactly one may be set, never both) -- the invariant this
    protects is `(result_json IS NOT NULL) XOR (result_ciphertext IS NOT
    NULL)` for results that carry a payload at all. `result_key_id` is
    NULL if and only if `result_ciphertext` is NULL, enforced the same way.

    `is_effective` + `ix_evidence_results_one_effective_per_type` (DE-003
    §11's duplicate-evidence-type finding): a session must have at most one
    non-superseded EvidenceResult per evidence_type. Nothing previously
    enforced this -- `supersede()` only ever added a new row, never marked
    the old one, so two independent create() calls for the same type could
    both remain "effective" simultaneously. `is_effective` is the same
    narrow-transition pattern as PolicyRecord's ACTIVE/SUPERSEDED partial
    unique index: superseding an existing result flips its `is_effective`
    to False in the same transaction that inserts the new (implicitly
    effective) row, and the partial unique index makes the database, not
    application logic, the final authority.
    """

    __tablename__ = "evidence_results"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "session_id",
            "idempotency_key",
            name="uq_evidence_results_tenant_session_idempotency",
        ),
        CheckConstraint(
            "result_json IS NULL OR result_ciphertext IS NULL",
            name="ck_evidence_results_payload_representation_exclusive",
        ),
        CheckConstraint(
            "(result_ciphertext IS NULL) = (result_key_id IS NULL)",
            name="ck_evidence_results_ciphertext_requires_key_id",
        ),
        Index("ix_evidence_results_tenant_session", "tenant_id", "session_id"),
        Index(
            "ix_evidence_results_tenant_session_type", "tenant_id", "session_id", "evidence_type"
        ),
        Index(
            "ix_evidence_results_one_effective_per_type",
            "tenant_id",
            "session_id",
            "evidence_type",
            unique=True,
            postgresql_where=text("is_effective = true"),
            sqlite_where=text("is_effective = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("verification_sessions.id"), nullable=False
    )
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # none_as_null=True: without it, SQLAlchemy's JSON type stores a Python
    # None as the JSON literal `null` rather than a SQL NULL, which would
    # defeat the "result_json IS NULL" half of the CHECK constraint above
    # (a row with the JSON null token present is NOT NULL to Postgres).
    result_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    result_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    result_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_codes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    producer: Mapped[str] = mapped_column(String(128), nullable=False)
    producer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_reference_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    source_reference: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("evidence.id"), nullable=True
    )
    parent_evidence_result_ids_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    supersedes_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("evidence_results.id"), nullable=True
    )
    produced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    persisted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    integrity_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_effective: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
