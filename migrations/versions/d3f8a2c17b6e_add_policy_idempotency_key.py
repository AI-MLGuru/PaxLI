"""add idempotency_key to policies

Invariant-12 remediation 1: policy activation retry-safety. Additive-only.

Revision ID: d3f8a2c17b6e
Revises: b7d4f1a08c3e
Create Date: 2026-09-10 16:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3f8a2c17b6e"
down_revision: str | Sequence[str] | None = "b7d4f1a08c3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("policies", sa.Column("idempotency_key", sa.String(256), nullable=True))
    op.create_unique_constraint(
        "uq_policies_tenant_idempotency", "policies", ["tenant_id", "idempotency_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_policies_tenant_idempotency", "policies", type_="unique")
    op.drop_column("policies", "idempotency_key")
