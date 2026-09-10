"""add credential scope

Revision ID: 02460b2dd296
Revises: 0041e99b1487
Create Date: 2026-09-10 05:42:18.118485

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "02460b2dd296"
down_revision: str | Sequence[str] | None = "0041e99b1487"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills existing rows as OPERATIONAL (the least-privileged
    # scope, per SEC-7.12.1: pre-Foundation-006 credentials must not silently
    # gain administrative permissions). Kept in place afterward as a safety net;
    # the application always sets scope explicitly on new rows.
    op.add_column(
        "credentials",
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="OPERATIONAL"),
    )


def downgrade() -> None:
    op.drop_column("credentials", "scope")
