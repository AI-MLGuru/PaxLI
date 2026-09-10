"""add rate_limit_windows table

Foundation-010: fixed-window rate limit persistence. Additive-only.

Revision ID: b7d4f1a08c3e
Revises: a1c3e6f9b2d4
Create Date: 2026-09-10 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d4f1a08c3e"
down_revision: str | Sequence[str] | None = "a1c3e6f9b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_windows",
        sa.Column("scope_key", sa.String(256), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_rate_limit_windows_window_start", "rate_limit_windows", ["window_start"])


def downgrade() -> None:
    op.drop_index("ix_rate_limit_windows_window_start", table_name="rate_limit_windows")
    op.drop_table("rate_limit_windows")
