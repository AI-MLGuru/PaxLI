"""add session policy pin (DE-004 Phase 4)

DE-002/DE-003 §1 early policy binding: VerificationSession gains
policy_id/policy_version/policy_hash, resolved once at creation via
PolicyService.get_active() and pinned forever (never re-resolved). Nullable
at the DB level for migration safety on the existing non-empty table --
sessions created before this column existed have no pin and stay that way;
every new session going forward always has one, enforced at
VerificationSession.create(), not by a DB constraint.

Revision ID: c2a7d9f14e6b
Revises: e8a4f2c6b910
Create Date: 2026-09-11 14:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2a7d9f14e6b"
down_revision: str | Sequence[str] | None = "e8a4f2c6b910"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("verification_sessions", sa.Column("policy_id", sa.String(128), nullable=True))
    op.add_column("verification_sessions", sa.Column("policy_version", sa.Integer(), nullable=True))
    op.add_column("verification_sessions", sa.Column("policy_hash", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("verification_sessions", "policy_hash")
    op.drop_column("verification_sessions", "policy_version")
    op.drop_column("verification_sessions", "policy_id")
