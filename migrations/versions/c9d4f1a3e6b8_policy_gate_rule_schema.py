"""policy gate/rule/threshold schema formalization (DE-003/DE-004)

Drops conflict_resolution_json (DE-002/DE-003 §7/§9: conflict handling is
folded into gates via GateKind.CONFLICT, not a separate policy construct)
and adds default_outcome (DE-003 §5/§10: an explicit, validated fallback
for "no rule matched", restricted to REJECTED/REVIEW_REQUIRED/INCONCLUSIVE,
never VERIFIED). evidence_requirements_json/gates_json/rules_json/
thresholds_json remain plain JSON columns -- only their Python-side
domain types changed (raw dicts -> typed Gate/Rule/EvidenceRequirement/
ThresholdDefinition), so no column-type DDL is needed for those.

Revision ID: c9d4f1a3e6b8
Revises: b3e7f1a94c2d
Create Date: 2026-09-11 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d4f1a3e6b8"
down_revision: str | Sequence[str] | None = "b3e7f1a94c2d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("policies", "conflict_resolution_json")
    op.add_column("policies", sa.Column("default_outcome", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("policies", "default_outcome")
    op.add_column("policies", sa.Column("conflict_resolution_json", sa.JSON(), nullable=True))
