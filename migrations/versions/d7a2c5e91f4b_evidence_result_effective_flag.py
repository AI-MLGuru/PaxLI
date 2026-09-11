"""evidence_results.is_effective + one-effective-per-type constraint

DE-003 §11 finding: nothing previously prevented two independent,
non-superseding EvidenceResult rows of the same evidence_type for one
session. `supersede()` only ever added a new row; it never marked the
original as no longer current. Adds `is_effective` (default true, so
every existing row is effective, matching current behavior) and a partial
unique index enforcing at most one effective row per
(tenant_id, session_id, evidence_type) -- same shape as
ix_policies_one_active_per_tenant_assurance.

Revision ID: d7a2c5e91f4b
Revises: c9d4f1a3e6b8
Create Date: 2026-09-11 10:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a2c5e91f4b"
down_revision: str | Sequence[str] | None = "c9d4f1a3e6b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evidence_results",
        sa.Column("is_effective", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(
        "ix_evidence_results_one_effective_per_type",
        "evidence_results",
        ["tenant_id", "session_id", "evidence_type"],
        unique=True,
        postgresql_where=sa.text("is_effective = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_results_one_effective_per_type", table_name="evidence_results")
    op.drop_column("evidence_results", "is_effective")
