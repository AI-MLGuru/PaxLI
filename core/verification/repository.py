from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from core.verification.enums import VerificationStatus
from core.verification.models import VerificationSession


class VerificationSessionRepository(Protocol):
    async def add(
        self, session: VerificationSession, idempotency_key: str | None = None
    ) -> VerificationSession:
        """Raises IdempotencyKeyConflictError (WF-001 §10) if a concurrent
        INSERT already claimed this (tenant_id, idempotency_key) -- the
        table's UNIQUE constraint is the final arbiter, never an
        application-level check-then-insert. The caller
        (VerificationSessionService.create()) recovers by re-fetching the
        winning row and comparing fingerprints, exactly like
        DecisionPersistenceService.persist() recovers from
        DecisionAlreadyExistsError."""
        ...

    async def get(self, session_id: UUID, tenant_id: str) -> VerificationSession | None: ...

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> VerificationSession | None: ...

    async def list(self, tenant_id: str) -> Sequence[VerificationSession]: ...

    async def update(
        self, session: VerificationSession, *, expected_status: VerificationStatus
    ) -> VerificationSession:
        """WF-001 §11: a compare-and-swap write, not a blind overwrite --
        `session` carries the FULL post-transition state (the caller
        already validated the transition's legality via
        VerificationSession.transition_to() before calling this), and
        `expected_status` is what the row's status must still be, at the
        database level, for the write to take effect. Zero rows affected
        (the row's status has already changed since the caller last read
        it, or the row doesn't exist for this tenant) raises
        ConcurrentTransitionError -- the database is the final arbiter on
        a concurrent lifecycle race, never an application-level
        check-then-write, matching every other race this codebase
        resolves this way (partial unique indexes, the decision
        persistence SAVEPOINT)."""
        ...
