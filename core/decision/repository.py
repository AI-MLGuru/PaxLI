from typing import Protocol
from uuid import UUID

from core.decision.models import DecisionProvenance


class DecisionRepository(Protocol):
    """No generic update() -- and no narrow named transition either, unlike
    every other repository in this codebase. A decision is fully immutable
    from the moment it is written (DEC-5.30.4: "historical decisions MUST
    NOT be silently overwritten"); there is no analogue of `mark_superseded`
    or `mark_not_effective` for a DecisionResult. The only two operations
    are `add` (write once) and reads."""

    async def add(self, provenance: DecisionProvenance) -> DecisionProvenance:
        """Raises DecisionAlreadyExistsError on a UNIQUE(tenant_id,
        session_id) conflict -- never silently returns the existing row
        itself; that recovery is the caller's (DecisionPersistenceService's)
        responsibility, matching every other repository's role in this
        codebase as a dumb constraint-violation translator, not a place
        business logic lives."""
        ...

    async def get(self, decision_id: UUID, tenant_id: str) -> DecisionProvenance | None: ...

    async def get_for_session(self, session_id: UUID, tenant_id: str) -> DecisionProvenance | None:
        """At most one row can ever exist for (tenant_id, session_id) -- the
        same UNIQUE constraint `add` relies on."""
        ...
