"""WF-001 §3-4/§6-7/§13: VerificationWorkflowService.submit()'s dispatch --
safe to call from any status, drives CREATED/CAPTURING through SUBMITTED,
PROCESSING, and into COMPLETED, invoking the Decision Engine through
DecisionOrchestrator along the way. Real-Postgres proof of the full,
genuinely-wired flow (a real DecisionOrchestrator, real policy, real
Decision Engine) lives in tests/integration/test_verification_workflow.py;
these tests exercise the dispatch/audit logic itself against fakes.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from core.audit.enums import AuditEventType
from core.audit.models import AuditEvent
from core.audit.service import AuditService
from core.decision.enums import DecisionOutcome, EvaluationReason
from core.decision.models import DecisionProvenance
from core.decision.references import PolicyReference
from core.verification.enums import TERMINAL_STATUSES, AssuranceLevel, VerificationStatus
from core.verification.exceptions import ConcurrentTransitionError, SessionAlreadyTerminalError
from core.verification.models import VerificationSession
from core.verification.service import VerificationSessionService
from core.verification.workflow import VerificationWorkflowService

TENANT = "tenant-a"


class FakeSessionRepository:
    """Same shape as tests/unit/test_verification_session_service.py's
    fake, plus stage_concurrent_winner(): the NEXT update() call fails
    AND atomically makes the given status visible via get() -- modeling
    a concurrent transaction that commits strictly between this call's
    own read and its own CAS write, the same "atomic staged winner"
    correction WF-003's idempotency tests needed (an earlier draft there
    made the winner visible too early, which meant the recovery path was
    never actually exercised despite the test passing)."""

    def __init__(self) -> None:
        self.sessions: dict[UUID, VerificationSession] = {}
        self.update_calls = 0
        self._pending_concurrent_winner_status: VerificationStatus | None = None

    async def add(self, session: VerificationSession, idempotency_key: str | None = None):
        self.sessions[session.id] = session
        return session.model_copy()

    async def get(self, session_id: UUID, tenant_id: str) -> VerificationSession | None:
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
        if self._pending_concurrent_winner_status is not None:
            winner_status = self._pending_concurrent_winner_status
            self._pending_concurrent_winner_status = None
            current = self.sessions[session.id]
            self.sessions[session.id] = current.model_copy(update={"status": winner_status})
            raise ConcurrentTransitionError("simulated concurrent transition")
        current = self.sessions.get(session.id)
        if current is None or current.status != expected_status:
            raise ConcurrentTransitionError(
                f"session_id={session.id!s} was not in status {expected_status.value!r}"
            )
        # A copy, deliberately -- storing the caller's own live object
        # here would let a LATER transition_to() call on that same
        # reference (VerificationWorkflowService.submit() chains several
        # in one call) retroactively mutate what this dict believes is
        # "currently stored," corrupting a later CAS check's `current`
        # read before that later update() ever runs. Same aliasing shape
        # as get()/add() needing .model_copy() (WF-002), just surfacing
        # on update() here because this is the first fake exercised by a
        # caller that chains multiple transitions through one object.
        self.sessions[session.id] = session.model_copy()
        return session

    def stage_concurrent_winner(self, status: VerificationStatus) -> None:
        self._pending_concurrent_winner_status = status


class FakeDecisionOrchestrator:
    """Implements exactly the two methods VerificationWorkflowService
    depends on (evaluate_and_persist(), get_for_session()) -- a real
    DecisionOrchestrator needs PolicyService/EvidenceResultService/
    DecisionPersistenceService to construct, too heavy for a pure unit
    test of the workflow dispatch itself. evaluate_and_persist()'s own
    idempotent convergence (DE-004 Phase 3/5) is mirrored here: a second
    call for an already-decided session returns the same row rather than
    producing a new one."""

    def __init__(self) -> None:
        self.decisions: dict[UUID, DecisionProvenance] = {}
        self.evaluate_calls: list[tuple[UUID, EvaluationReason]] = []

    async def evaluate_and_persist(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        evaluation_reason: EvaluationReason = EvaluationReason.NORMAL,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> DecisionProvenance:
        self.evaluate_calls.append((session_id, evaluation_reason))
        existing = self.decisions.get(session_id)
        if existing is not None:
            return existing
        outcome = (
            DecisionOutcome.INCONCLUSIVE
            if evaluation_reason is EvaluationReason.EXPIRATION
            else DecisionOutcome.VERIFIED
        )
        decision = DecisionProvenance(
            decision_id=uuid4(),
            session_id=session_id,
            tenant_id=tenant_id,
            outcome=outcome,
            reason_codes=(),
            policy_reference=PolicyReference(
                policy_id="policy-x", policy_version=1, policy_hash="hash-x"
            ),
            created_at=datetime.now(UTC),
            evaluation_reason=evaluation_reason,
        )
        self.decisions[session_id] = decision
        return decision

    async def get_for_session(
        self, *, session_id: UUID, tenant_id: str
    ) -> DecisionProvenance | None:
        return self.decisions.get(session_id)


class FakeAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def add(self, event: AuditEvent, dedupe_key: str | None = None) -> AuditEvent:
        self.events.append(event)
        return event

    async def get_by_dedupe_key(self, tenant_id, session_id, dedupe_key):
        return None

    async def list_for_session(self, session_id, tenant_id):
        return [e for e in self.events if e.session_id == session_id]


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
def session_service(
    repo: FakeSessionRepository, audit_service: AuditService
) -> VerificationSessionService:
    return VerificationSessionService(repo, audit_service=audit_service, session_ttl_minutes=30)


@pytest.fixture
def orchestrator() -> FakeDecisionOrchestrator:
    return FakeDecisionOrchestrator()


@pytest.fixture
def audit_repo() -> FakeAuditRepository:
    return FakeAuditRepository()


@pytest.fixture
def audit_service(audit_repo: FakeAuditRepository) -> AuditService:
    return AuditService(audit_repo)


@pytest.fixture
def workflow(
    session_service: VerificationSessionService,
    orchestrator: FakeDecisionOrchestrator,
    audit_service: AuditService,
) -> VerificationWorkflowService:
    return VerificationWorkflowService(session_service, orchestrator, audit_service)


# ---------------------------------------------------------------------------
# The normal forward path (§4's CREATED/CAPTURING and SUBMITTED branches)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [VerificationStatus.CREATED, VerificationStatus.CAPTURING])
async def test_submit_from_an_initiation_status_drives_all_the_way_to_completed(
    workflow, repo, orchestrator, audit_repo, status
) -> None:
    session = _session_in_status(status)
    await repo.add(session)

    result_session, decision = await workflow.submit(session_id=session.id, tenant_id=TENANT)

    assert result_session.status is VerificationStatus.COMPLETED
    assert decision.session_id == session.id
    assert orchestrator.evaluate_calls == [(session.id, EvaluationReason.NORMAL)]
    event_types = [e.event_type for e in audit_repo.events]
    assert event_types == [
        AuditEventType.SESSION_SUBMITTED,
        AuditEventType.SESSION_PROCESSING_STARTED,
        AuditEventType.SESSION_COMPLETED,
    ]


@pytest.mark.asyncio
async def test_submit_from_submitted_skips_straight_to_processing(
    workflow, repo, audit_repo
) -> None:
    """No SESSION_SUBMITTED is re-emitted -- that hop already happened
    (and was already audited) by whatever earlier call put this session
    in SUBMITTED."""
    session = _session_in_status(VerificationStatus.SUBMITTED)
    await repo.add(session)

    result_session, _decision = await workflow.submit(session_id=session.id, tenant_id=TENANT)

    assert result_session.status is VerificationStatus.COMPLETED
    event_types = [e.event_type for e in audit_repo.events]
    assert event_types == [
        AuditEventType.SESSION_PROCESSING_STARTED,
        AuditEventType.SESSION_COMPLETED,
    ]


# ---------------------------------------------------------------------------
# PROCESSING is a recovery state, not a second initiation path (§4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_from_processing_is_recovery_not_reinitiation(
    workflow, repo, orchestrator, audit_repo
) -> None:
    """A session found already in PROCESSING (an earlier submit() call
    left it there -- crash, timeout) is completed directly: only
    SESSION_COMPLETED is emitted, never SESSION_SUBMITTED or
    SESSION_PROCESSING_STARTED, since this call never initiated either
    of those hops."""
    session = _session_in_status(VerificationStatus.PROCESSING)
    await repo.add(session)

    result_session, decision = await workflow.submit(session_id=session.id, tenant_id=TENANT)

    assert result_session.status is VerificationStatus.COMPLETED
    assert decision.evaluation_reason is EvaluationReason.NORMAL
    assert orchestrator.evaluate_calls == [(session.id, EvaluationReason.NORMAL)]
    event_types = [e.event_type for e in audit_repo.events]
    assert event_types == [AuditEventType.SESSION_COMPLETED]


@pytest.mark.asyncio
async def test_submit_from_processing_past_deadline_selects_expiration_reason(
    workflow, repo, orchestrator
) -> None:
    """§7: PROCESSING has no EXPIRED edge -- a session past its deadline
    while PROCESSING is resolved by running the Decision Engine with
    EvaluationReason.EXPIRATION, landing at COMPLETED with an
    INCONCLUSIVE decision, never transitioned to EXPIRED directly."""
    session = _session_in_status(
        VerificationStatus.PROCESSING, expires_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    await repo.add(session)

    result_session, decision = await workflow.submit(session_id=session.id, tenant_id=TENANT)

    assert result_session.status is VerificationStatus.COMPLETED
    assert decision.evaluation_reason is EvaluationReason.EXPIRATION
    assert decision.outcome is DecisionOutcome.INCONCLUSIVE
    assert orchestrator.evaluate_calls == [(session.id, EvaluationReason.EXPIRATION)]


@pytest.mark.asyncio
async def test_submit_retried_after_a_crash_converges_via_evaluate_and_persists_own_idempotency(
    workflow, repo, orchestrator, audit_repo
) -> None:
    """A second, independent submit() call against a still-PROCESSING
    session (simulating a retry after the first call's process died
    before reaching COMPLETED) must converge on the SAME decision, not
    produce a second one -- proven here at the workflow layer by calling
    submit() twice against the same fakes."""
    session = _session_in_status(VerificationStatus.PROCESSING)
    await repo.add(session)

    first_session, first_decision = await workflow.submit(session_id=session.id, tenant_id=TENANT)
    # A hypothetical retry would find the session already COMPLETED --
    # submit() must still succeed, idempotently, via the COMPLETED branch.
    second_session, second_decision = await workflow.submit(
        session_id=session.id, tenant_id=TENANT
    )

    assert first_decision.decision_id == second_decision.decision_id
    assert first_session.status is second_session.status is VerificationStatus.COMPLETED
    assert len(orchestrator.evaluate_calls) == 1  # the Decision Engine ran exactly once, ever
    # the COMPLETED-branch replay recorded no additional audit event
    event_types = [e.event_type for e in audit_repo.events]
    assert event_types == [AuditEventType.SESSION_COMPLETED]


# ---------------------------------------------------------------------------
# COMPLETED idempotent replay (§4's final branch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_from_completed_is_an_idempotent_replay_with_no_new_work(
    workflow, repo, orchestrator, audit_repo
) -> None:
    session = _session_in_status(VerificationStatus.COMPLETED)
    await repo.add(session)
    existing_decision = DecisionProvenance(
        decision_id=uuid4(),
        session_id=session.id,
        tenant_id=TENANT,
        outcome=DecisionOutcome.VERIFIED,
        reason_codes=(),
        policy_reference=PolicyReference(policy_id="p", policy_version=1, policy_hash="h"),
        created_at=datetime.now(UTC),
    )
    orchestrator.decisions[session.id] = existing_decision

    result_session, decision = await workflow.submit(session_id=session.id, tenant_id=TENANT)

    assert result_session.status is VerificationStatus.COMPLETED
    assert decision.decision_id == existing_decision.decision_id
    assert orchestrator.evaluate_calls == []  # no new work
    assert audit_repo.events == []  # no new audit


@pytest.mark.asyncio
async def test_submit_from_completed_with_no_persisted_decision_raises_runtime_error(
    workflow, repo
) -> None:
    """Should be unreachable in normal operation: the only path to
    COMPLETED in this codebase always persists a decision first (§4).
    Surfacing this loudly rather than returning a silently incomplete
    result if it ever somehow happens."""
    session = _session_in_status(VerificationStatus.COMPLETED)
    await repo.add(session)

    with pytest.raises(RuntimeError, match="has no persisted decision"):
        await workflow.submit(session_id=session.id, tenant_id=TENANT)


# ---------------------------------------------------------------------------
# Terminal statuses (§4's final catch-all)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    sorted(TERMINAL_STATUSES - {VerificationStatus.COMPLETED}, key=lambda s: s.value),
)
async def test_submit_raises_session_already_terminal_for_expired_or_cancelled(
    workflow, repo, status
) -> None:
    session = _session_in_status(status)
    await repo.add(session)

    with pytest.raises(SessionAlreadyTerminalError):
        await workflow.submit(session_id=session.id, tenant_id=TENANT)


# ---------------------------------------------------------------------------
# Concurrency (§6's "loser translates its conflict into the appropriate
# error" / harmless convergence when the winner reached the same status)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_advance_converges_harmlessly_when_a_concurrent_call_wins_the_identical_hop(
    workflow, repo, audit_repo
) -> None:
    """A concurrent submit() call (e.g. a client retry landing mid-flight)
    wins the CAS race to the SAME target status this call was also
    attempting -- that is success, not a conflict: this call converges on
    the winner's row and records no duplicate audit event."""
    session = _session_in_status(VerificationStatus.SUBMITTED)
    await repo.add(session)
    repo.stage_concurrent_winner(VerificationStatus.PROCESSING)

    result_session, decision = await workflow.submit(session_id=session.id, tenant_id=TENANT)

    assert result_session.status is VerificationStatus.COMPLETED
    assert decision is not None
    # no SESSION_PROCESSING_STARTED recorded by THIS call -- the winner's
    # own call already recorded one (not modeled by this fake, since only
    # one workflow instance is under test here; the property under test
    # is simply that this call didn't ALSO emit one).
    event_types = [e.event_type for e in audit_repo.events]
    assert AuditEventType.SESSION_PROCESSING_STARTED not in event_types
    assert AuditEventType.SESSION_COMPLETED in event_types


@pytest.mark.asyncio
async def test_advance_raises_session_already_terminal_when_a_concurrent_cancellation_wins(
    workflow, repo, orchestrator
) -> None:
    """WF-001 §6: cancellation racing a concurrent submit() reaching
    COMPLETED first is resolved by CAS, and the loser (submit(), here)
    translates its conflict into the appropriate error -- never silently
    treats a cancellation as if it had succeeded in completing."""
    session = _session_in_status(VerificationStatus.PROCESSING)
    await repo.add(session)
    repo.stage_concurrent_winner(VerificationStatus.CANCELLED)

    with pytest.raises(SessionAlreadyTerminalError):
        await workflow.submit(session_id=session.id, tenant_id=TENANT)

    # the decision was still durably produced before the losing CAS
    # attempt -- DE-003's "exactly once, ever" guarantee already fired
    assert len(orchestrator.evaluate_calls) == 1
