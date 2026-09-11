"""add decisions table (DE-004 Phase 3)

Persists core.decision.models.DecisionProvenance. `uq_decisions_tenant_session`
is the load-bearing constraint (DE-003 §14): a session is evaluated to a
durable decision exactly once, ever -- the database, not application logic,
is the final authority, same discipline as
ix_policies_one_active_per_tenant_assurance and
ix_evidence_results_one_effective_per_type.

`evidence_references_json`/`model_references_json`/
`calibration_references_json` are plain JSON columns with no foreign key --
deliberate (DE-002 landmine 1 / DE-003 §12): a decision must survive the
deletion of evidence it consumed, so nothing here may hard-reference a
deletable evidence_results row.

Revision ID: e8a4f2c6b910
Revises: d7a2c5e91f4b
Create Date: 2026-09-11 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8a4f2c6b910"
down_revision: str | Sequence[str] | None = "d7a2c5e91f4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("verification_sessions.id"),
            nullable=False,
        ),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("reason_codes_json", sa.JSON(), nullable=False),
        sa.Column("policy_id", sa.String(128), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("policy_hash", sa.String(128), nullable=False),
        sa.Column("evidence_references_json", sa.JSON(), nullable=False),
        sa.Column("model_references_json", sa.JSON(), nullable=False),
        sa.Column("calibration_references_json", sa.JSON(), nullable=False),
        sa.Column("prohibited_types_present_json", sa.JSON(), nullable=False),
        sa.Column("evaluation_reason", sa.String(32), nullable=False),
        sa.Column("engine_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_unique_constraint(
        "uq_decisions_tenant_session", "decisions", ["tenant_id", "session_id"]
    )
    op.create_index("ix_decisions_tenant_session", "decisions", ["tenant_id", "session_id"])


def downgrade() -> None:
    op.drop_index("ix_decisions_tenant_session", table_name="decisions")
    op.drop_constraint("uq_decisions_tenant_session", "decisions", type_="unique")
    op.drop_table("decisions")
