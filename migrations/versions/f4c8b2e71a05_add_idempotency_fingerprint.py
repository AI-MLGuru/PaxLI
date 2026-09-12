"""add idempotency fingerprint (WF-003 / WF-001 §10)

WF-4.9.3 / API-6.12.2: materially different reuse of an Idempotency-Key
MUST be rejected, not silently resolved to whichever request wrote first.
Both verification_sessions and evidence gain a nullable fingerprint column
-- sha256(canonical_json(...)) of the request fields that define "what was
being created" -- so a replayed key can be compared against what was
actually persisted, not merely matched by key alone.

Nullable at the DB level for migration safety on the existing non-empty
tables -- rows created before this column existed have no fingerprint and
stay that way; every new row going forward always has one, enforced at
VerificationSession.create()/EvidenceService.add(), not by a DB constraint.

Revision ID: f4c8b2e71a05
Revises: c2a7d9f14e6b
Create Date: 2026-09-11 17:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4c8b2e71a05"
down_revision: str | Sequence[str] | None = "c2a7d9f14e6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("verification_sessions", sa.Column("fingerprint", sa.String(128), nullable=True))
    op.add_column("evidence", sa.Column("fingerprint", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("evidence", "fingerprint")
    op.drop_column("verification_sessions", "fingerprint")
