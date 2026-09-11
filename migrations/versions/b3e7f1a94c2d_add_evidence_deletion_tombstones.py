"""add evidence and evidence-result deletion tombstones

Invariant-06 remediation Phase 2: persistence for the two-phase
(requested_at / executed_at) deletion tombstone. Additive-only -- the
existing `evidence` and `evidence_results` tables are untouched.

`evidence_id` / `evidence_result_id` are primary keys, not foreign keys:
by the time Phase-2 reconciliation completes, the referenced row has been
physically deleted, so a foreign-key constraint against it would break the
moment deletion actually succeeds. The primary key alone enforces "one
tombstone per deleted resource".

Revision ID: b3e7f1a94c2d
Revises: f2b7e60c9a3d
Create Date: 2026-09-11 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3e7f1a94c2d"
down_revision: str | Sequence[str] | None = "f2b7e60c9a3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DELETION_BASIS_VALUES = (
    "TENANT_REQUEST",
    "DATA_SUBJECT_REQUEST",
    "RETENTION_EXPIRY",
    "LEGAL_REQUIREMENT",
    "OTHER_AUTHORIZED_BASIS",
)


def upgrade() -> None:
    op.create_table(
        "evidence_tombstones",
        sa.Column("evidence_id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id", sa.String(36), sa.ForeignKey("verification_sessions.id"), nullable=False
        ),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("deletion_basis", sa.String(32), nullable=False),
        sa.Column("basis_reference", sa.String(512)),
        sa.Column("authorized_by", sa.String(256), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("evidence_integrity_reference", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "deletion_basis IN ("
            + ", ".join(f"'{value}'" for value in _DELETION_BASIS_VALUES)
            + ")",
            name="ck_evidence_tombstones_deletion_basis",
        ),
        sa.CheckConstraint(
            "executed_at IS NULL OR executed_at >= requested_at",
            name="ck_evidence_tombstones_executed_after_requested",
        ),
    )
    op.create_index("ix_evidence_tombstones_tenant", "evidence_tombstones", ["tenant_id"])

    op.create_table(
        "evidence_result_tombstones",
        sa.Column("evidence_result_id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id", sa.String(36), sa.ForeignKey("verification_sessions.id"), nullable=False
        ),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("deletion_basis", sa.String(32), nullable=False),
        sa.Column("basis_reference", sa.String(512)),
        sa.Column("authorized_by", sa.String(256), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("evidence_integrity_reference", sa.String(128), nullable=False),
        sa.CheckConstraint(
            "deletion_basis IN ("
            + ", ".join(f"'{value}'" for value in _DELETION_BASIS_VALUES)
            + ")",
            name="ck_evidence_result_tombstones_deletion_basis",
        ),
        sa.CheckConstraint(
            "executed_at IS NULL OR executed_at >= requested_at",
            name="ck_evidence_result_tombstones_executed_after_requested",
        ),
    )
    op.create_index(
        "ix_evidence_result_tombstones_tenant", "evidence_result_tombstones", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_result_tombstones_tenant", table_name="evidence_result_tombstones")
    op.drop_table("evidence_result_tombstones")
    op.drop_index("ix_evidence_tombstones_tenant", table_name="evidence_tombstones")
    op.drop_table("evidence_tombstones")
