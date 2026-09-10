"""add evidence_results table

Foundation-008: Part III evidence-result persistence. Additive-only -- the
existing `evidence` table (Foundation-003's capture storage) is untouched.

Revision ID: c2abf2f94440
Revises: 02460b2dd296
Create Date: 2026-09-10 08:26:47.051377

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2abf2f94440"
down_revision: str | Sequence[str] | None = "02460b2dd296"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column(
            "session_id", sa.String(36), sa.ForeignKey("verification_sessions.id"), nullable=False
        ),
        sa.Column("evidence_type", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result_json", sa.JSON()),
        sa.Column("result_ciphertext", sa.LargeBinary()),
        sa.Column("result_key_id", sa.String(64)),
        sa.Column("reason_codes_json", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float()),
        sa.Column("quality", sa.Float()),
        sa.Column("producer", sa.String(128), nullable=False),
        sa.Column("producer_version", sa.String(64), nullable=False),
        sa.Column("model_reference_json", sa.JSON()),
        sa.Column("source_reference", sa.String(36), sa.ForeignKey("evidence.id")),
        sa.Column("parent_evidence_result_ids_json", sa.JSON(), nullable=False),
        sa.Column("supersedes_id", sa.String(36), sa.ForeignKey("evidence_results.id")),
        sa.Column("produced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("persisted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("integrity_reference", sa.String(128), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "result_json IS NULL OR result_ciphertext IS NULL",
            name="ck_evidence_results_payload_representation_exclusive",
        ),
        sa.CheckConstraint(
            "(result_ciphertext IS NULL) = (result_key_id IS NULL)",
            name="ck_evidence_results_ciphertext_requires_key_id",
        ),
    )
    op.create_index(
        "ix_evidence_results_tenant_session", "evidence_results", ["tenant_id", "session_id"]
    )
    op.create_index(
        "ix_evidence_results_tenant_session_type",
        "evidence_results",
        ["tenant_id", "session_id", "evidence_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_results_tenant_session_type", table_name="evidence_results")
    op.drop_index("ix_evidence_results_tenant_session", table_name="evidence_results")
    op.drop_table("evidence_results")
