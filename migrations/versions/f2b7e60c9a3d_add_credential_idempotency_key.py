"""add idempotency_key to credentials

Invariant-12 remediation 1: credential issue/rotate retry-safety. Additive-only.

Revision ID: f2b7e60c9a3d
Revises: e5a9c4d28f1a
Create Date: 2026-09-10 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2b7e60c9a3d"
down_revision: str | Sequence[str] | None = "e5a9c4d28f1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("credentials", sa.Column("idempotency_key", sa.String(256), nullable=True))
    op.create_unique_constraint(
        "uq_credentials_tenant_idempotency", "credentials", ["tenant_id", "idempotency_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_credentials_tenant_idempotency", "credentials", type_="unique")
    op.drop_column("credentials", "idempotency_key")
