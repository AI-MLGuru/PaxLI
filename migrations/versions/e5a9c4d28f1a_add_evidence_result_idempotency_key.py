"""add idempotency_key to evidence_results

Invariant-12 remediation 1: evidence-result creation retry-safety. Additive-only.

Revision ID: e5a9c4d28f1a
Revises: d3f8a2c17b6e
Create Date: 2026-09-10 16:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5a9c4d28f1a"
down_revision: str | Sequence[str] | None = "d3f8a2c17b6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("evidence_results", sa.Column("idempotency_key", sa.String(256), nullable=True))
    op.create_unique_constraint(
        "uq_evidence_results_tenant_session_idempotency",
        "evidence_results",
        ["tenant_id", "session_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_evidence_results_tenant_session_idempotency", "evidence_results", type_="unique"
    )
    op.drop_column("evidence_results", "idempotency_key")
