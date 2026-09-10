"""add policies table

Foundation-009: Part V policy governance persistence. Additive-only.

Revision ID: a1c3e6f9b2d4
Revises: c2abf2f94440
Create Date: 2026-09-10 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c3e6f9b2d4"
down_revision: str | Sequence[str] | None = "c2abf2f94440"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("policy_id", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("assurance_level", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("evidence_requirements_json", sa.JSON(), nullable=False),
        sa.Column("conditions_json", sa.JSON()),
        sa.Column("gates_json", sa.JSON(), nullable=False),
        sa.Column("rules_json", sa.JSON(), nullable=False),
        sa.Column("thresholds_json", sa.JSON(), nullable=False),
        sa.Column("conflict_resolution_json", sa.JSON()),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("canonical_hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("supersedes_id", sa.String(36), sa.ForeignKey("policies.id")),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "policy_id", "version", name="uq_policies_tenant_version"
        ),
        sa.CheckConstraint(
            "(status = 'SUPERSEDED') = (superseded_at IS NOT NULL)",
            name="ck_policies_superseded_at_matches_status",
        ),
    )
    op.create_index("ix_policies_tenant_policy", "policies", ["tenant_id", "policy_id"])
    op.create_index(
        "ix_policies_one_active_per_tenant_assurance",
        "policies",
        ["tenant_id", "assurance_level"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_index("ix_policies_one_active_per_tenant_assurance", table_name="policies")
    op.drop_index("ix_policies_tenant_policy", table_name="policies")
    op.drop_table("policies")
