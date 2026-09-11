"""WF-001 §6/§7/§11: cancellation, lazy expiration, and the compare-and-
swap lifecycle transition, against in-memory fakes. Real-Postgres proof
of the CAS mechanism under a genuine concurrent race lives in
tests/integration/test_verification_session_service.py.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from core.verification.enums import TERMINAL_STATUSES, AssuranceLevel, VerificationStatus
from core.verification.exceptions import (
    ConcurrentTransitionError,
    SessionAlreadyTerminalError,
    SessionNotFoundError,
)
from core.verification.models import VerificationSession
from core.verification.service import VerificationSessionService

TENANT = "tenant-a"

CANCELLABLE_STATUSES = (
    VerificationStatus.CREATED,
    VerificationStatus.CAPTURING,
    VerificationStatus.SUBMITTED,
    VerificationStatus.PROCESSING,
)


class FakeSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, VerificationSession] = {}
        self.update_calls = 0
        # When set, the NEXT update() call raises this instead of applying
        # the write -- used to simulate a race the fake's own natural
        # sequential-dict semantics can't otherwise produce.
        self.raise_on_next_update: Exception | None = None

    async def add(self, session: VerificationSession, idempotency_key: str | None = None):
        self.sessions[session.id] = session
        return session.model_copy()

    async def get(self, session_id: UUID, tenant_id: str) -> VerificationSession | None:
        # A fresh copy, deliberately -- a real DB-backed repository
        # reconstructs a new domain object from persisted columns on every
        # read; it never hands back a live reference the caller could
        # mutate and have that mutation silently visible to a LATER read
        # (or to this fake's own "stored" state) before any write actually
        # happens. Returning the same object here would let
        # transition_to()'s in-place mutation corrupt the CAS check below
        # before update() ever runs.
        session = self.sessions.get(session_id)
        if session is None or session.tenant_id != tenant_id:
            return None
        return session.model_copy()

    async def get_by_idempotency_key(self, tenant_id: str, idempotency_key: str):
        return None

    async def list(self, tenant_id: str):
        return [s for s in self.sessions.values() if s.tenant_id == tenant_id]

    async def update(
        self, session: VerificationSession, *, expected_status: VerificationStatus
    ) -> VerificationSession:
        self.update_calls += 1
        if self.raise_on_next_update is not None:
            exc = self.raise_on_next_update
            self.raise_on_next_update = None
            raise exc
        current = self.sessions.get(session.id)
        if current is None or current.status != expected_status:
            raise ConcurrentTransitionError(
                f"session_id={session.id!s} was not in status {expected_status.value!r}"
            )
        self.sessions[session.id] = session
        return session


def _session_in_status(
    status: VerificationStatus, *, expires_at: datetime | None = None
) -> VerificationSession:
    now = datetime.now(UTC)
    return VerificationSession(
        tenant_id=TENANT,
        status=status,
        assurance_level=AssuranceLevel.STANDARD,
        created_at=now,
        expires_at=expires_at or (now + timedelta(hours=1)),
    )


@pytest.fixture
def repo() -> FakeSessionRepository:
    return FakeSessionRepository()


@pytest.fixture
def service(repo: FakeSessionRepository) -> VerificationSessionService:
    return VerificationSessionService(repo, session_ttl_minutes=30)


# ---------------------------------------------------------------------------
# Cancellation (WF-001 §6, Finding 5's fix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", CANCELLABLE_STATUSES)
async def test_cancel_succeeds_from_every_non_terminal_status(service, repo, status) -> None:
    session = _session_in_status(status)
    await repo.add(session)

    cancelled = await service.cancel(session_id=session.id, tenant_id=TENANT)

    assert cancelled.status is VerificationStatus.CANCELLED
    assert cancelled.completed_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES, key=lambda s: s.value))
async def test_cancel_raises_a_named_conflict_never_a_bare_value_error(
    service, repo, status
) -> None:
    """Finding 5: the exact bug this closes. Cancelling an already-
    terminal session must raise SessionAlreadyTerminalError -- never let
    VerificationSession.transition_to()'s internal ValueError escape
    uncaught (which would previously have surfaced as an unhandled 500)."""
    session = _session_in_status(status)
    await repo.add(session)

    with pytest.raises(SessionAlreadyTerminalError):
        await service.cancel(session_id=session.id, tenant_id=TENANT)

    # nothing was mutated by the failed attempt
    assert repo.sessions[session.id].status is status


@pytest.mark.asyncio
async def test_cancel_a_nonexistent_session_raises_session_not_found(service) -> None:
    with pytest.raises(SessionNotFoundError):
        await service.cancel(session_id=uuid4(), tenant_id=TENANT)


@pytest.mark.asyncio
async def test_cancel_propagates_a_genuine_concurrent_transition_conflict(service, repo) -> None:
    """WF-001 §6: unlike get()'s lazy expire, cancellation is an explicit,
    client-intent-driven request -- losing a CAS race must surface as a
    real conflict, not be silently swallowed."""
    session = _session_in_status(VerificationStatus.PROCESSING)
    await repo.add(session)
    repo.raise_on_next_update = ConcurrentTransitionError("simulated concurrent completion")

    with pytest.raises(ConcurrentTransitionError):
        await service.cancel(session_id=session.id, tenant_id=TENANT)


# ---------------------------------------------------------------------------
# Lazy expiration (WF-001 §7) and its CAS interaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [VerificationStatus.CREATED, VerificationStatus.CAPTURING, VerificationStatus.SUBMITTED],
)
async def test_get_lazily_expires_every_pre_processing_status_past_its_deadline(
    service, repo, status
) -> None:
    session = _session_in_status(status, expires_at=datetime.now(UTC) - timedelta(minutes=1))
    await repo.add(session)

    fetched = await service.get(session_id=session.id, tenant_id=TENANT)

    assert fetched.status is VerificationStatus.EXPIRED
    assert repo.sessions[session.id].status is VerificationStatus.EXPIRED


@pytest.mark.asyncio
async def test_get_never_lazily_expires_a_processing_session() -> None:
    """WF-001 §7's exact distinction: a PROCESSING session past its
    deadline must NOT be transitioned to EXPIRED by this lazy check --
    that case is resolved by running the Decision Engine with
    EvaluationReason.EXPIRATION and landing at COMPLETED, which is the
    workflow orchestration boundary's job (WF-004), not this one."""
    session = _session_in_status(
        VerificationStatus.PROCESSING, expires_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    assert session.expire_if_needed() is False
    assert session.status is VerificationStatus.PROCESSING


@pytest.mark.asyncio
async def test_get_swallows_a_lost_expire_race_and_returns_current_truth(service, repo) -> None:
    """A concurrent write (another request's own lazy expire, or a real
    workflow transition) already resolved this session's status --
    get()'s opportunistic side-effect write loses the race, and that must
    be harmless to the caller, which only ever asked to read."""
    session = _session_in_status(
        VerificationStatus.CREATED, expires_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    await repo.add(session)
    # Simulate: by the time get()'s own update() call runs, some other
    # process already cancelled the session.
    repo.raise_on_next_update = ConcurrentTransitionError("simulated concurrent cancellation")
    repo.sessions[session.id] = session.model_copy(update={"status": VerificationStatus.CANCELLED})

    fetched = await service.get(session_id=session.id, tenant_id=TENANT)

    assert fetched.status is VerificationStatus.CANCELLED  # the current truth, not EXPIRED


@pytest.mark.asyncio
async def test_get_of_a_healthy_session_never_calls_update(service, repo) -> None:
    session = _session_in_status(VerificationStatus.CREATED)
    await repo.add(session)

    await service.get(session_id=session.id, tenant_id=TENANT)

    assert repo.update_calls == 0


# ---------------------------------------------------------------------------
# Transition table (WF-001 §1)
# ---------------------------------------------------------------------------


def test_processing_cannot_transition_directly_to_expired() -> None:
    """The one deliberately-missing edge in the whole table (WF-001 §1's
    landmine): PROCESSING has no EXPIRED edge at all. A session that
    reached PROCESSING always ends up with a DecisionResult, even when
    that result is the expiration-forced INCONCLUSIVE."""
    session = _session_in_status(VerificationStatus.PROCESSING)
    with pytest.raises(ValueError, match="Invalid session transition"):
        session.transition_to(VerificationStatus.EXPIRED)


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (VerificationStatus.CREATED, VerificationStatus.CAPTURING),
        (VerificationStatus.CREATED, VerificationStatus.SUBMITTED),
        (VerificationStatus.CAPTURING, VerificationStatus.SUBMITTED),
        (VerificationStatus.SUBMITTED, VerificationStatus.PROCESSING),
        (VerificationStatus.PROCESSING, VerificationStatus.COMPLETED),
    ],
)
def test_the_normal_forward_path_is_legal(start, target) -> None:
    session = _session_in_status(start)
    session.transition_to(target)
    assert session.status is target


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES, key=lambda s: s.value))
def test_every_terminal_status_has_no_outgoing_transition(status) -> None:
    session = _session_in_status(status)
    for target in VerificationStatus:
        if target is status:
            continue
        with pytest.raises(ValueError, match="Invalid session transition"):
            session.transition_to(target)
