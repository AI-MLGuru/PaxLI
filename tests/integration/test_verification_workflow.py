"""Real PostgreSQL integration tests for WF-001 §3-4/§7/§13's workflow
orchestration boundary -- the full pipeline, end to end, against real
infrastructure: activate a policy, create a session, submit(), and verify
the persisted session AND decision, with nothing faked. Mirrors
tests/integration/test_decision_orchestration.py's DI-wiring pattern, one
layer up. Skipped when Postgres isn't reachable.
"""

import asyncio
import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from apps.api.paxli_api.config import get_settings
from core.audit.enums import AuditEventType
from core.audit.service import AuditService
from core.decision.enums import DecisionOutcome, EngineReasonCode, EvaluationReason
from core.decision.orchestration import DecisionOrchestrator
from core.decision.persistence import DecisionPersistenceService
from core.document.deterministic import (
    DeterministicBarcodeDecoder,
    DeterministicDocumentClassifier,
    DeterministicFieldReconciler,
    DeterministicMRZParser,
    DeterministicOCREngine,
    DeterministicQualityAssessor,
)
from core.evidence.enums import EvidenceType
from core.evidence.service import EvidenceService
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.evidence_result.service import EvidenceResultService
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel, VerificationStatus
from core.verification.exceptions import ConcurrentTransitionError, SessionAlreadyTerminalError
from core.verification.service import VerificationSessionService
from core.verification.workflow import VerificationWorkflowService
from infrastructure.database.models.decision import DecisionRecord
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.decision import SqlAlchemyDecisionRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import SqlAlchemyEvidenceResultRepository
from infrastructure.database.repositories.policy import SqlAlchemyVerificationPolicyRepository
from infrastructure.database.repositories.verification_session import (
    SqlAlchemyVerificationSessionRepository,
)
from infrastructure.database.session import session_factory
from infrastructure.document.processor import SqlAlchemyDocumentProcessor
from infrastructure.security.local_key_provider import LocalAesGcmKeyProvider
from infrastructure.storage.encrypted import EncryptedObjectStorage
from infrastructure.storage.minio import MinioObjectStorage

MINIMAL_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"


def _postgres_reachable() -> bool:
    url = urlparse(get_settings().database_url.replace("+asyncpg", ""))
    try:
        with socket.create_connection((url.hostname, url.port or 5432), timeout=1):
            return True
    except OSError:
        return False


def _minio_reachable() -> bool:
    settings = get_settings()
    host, _, port = settings.storage_endpoint.partition(":")
    try:
        with socket.create_connection((host, int(port) if port else 9000), timeout=1):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.skipif(
        not (_postgres_reachable() and _minio_reachable()),
        reason="PostgreSQL and/or MinIO not reachable",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


@pytest.fixture(scope="module", autouse=True)
async def _dispose_shared_engine_pool_after_module():
    from infrastructure.database.session import engine

    yield
    await engine.dispose()


_KEY_PROVIDER = LocalAesGcmKeyProvider({"test-workflow-key": b"0" * 32})


def _services(session):
    policy_service = PolicyService(
        SqlAlchemyVerificationPolicyRepository(session),
        AuditService(SqlAlchemyAuditEventRepository(session)),
        EvidenceResultSchemaCatalog(),
    )
    session_service = VerificationSessionService(
        SqlAlchemyVerificationSessionRepository(session),
        audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
        policy_service=policy_service,
        session_ttl_minutes=30,
    )
    evidence_result_service = EvidenceResultService(
        SqlAlchemyEvidenceResultRepository(session, _KEY_PROVIDER, "test-workflow-key"),
        AuditService(SqlAlchemyAuditEventRepository(session)),
        SqlAlchemyEvidenceRepository(session),
    )
    audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
    persistence_service = DecisionPersistenceService(
        SqlAlchemyDecisionRepository(session), audit_service
    )
    orchestrator = DecisionOrchestrator(
        session_service, policy_service, evidence_result_service, persistence_service, audit_service
    )
    document_processor = SqlAlchemyDocumentProcessor(
        session_factory,
        _KEY_PROVIDER,
        "test-workflow-key",
        _evidence_storage(),
        DeterministicQualityAssessor(),
        DeterministicDocumentClassifier(),
        DeterministicMRZParser(),
        DeterministicBarcodeDecoder(),
        DeterministicOCREngine(),
        DeterministicFieldReconciler(),
    )
    workflow = VerificationWorkflowService(
        session_service, orchestrator, audit_service, document_processor
    )
    return policy_service, session_service, orchestrator, audit_service, workflow


def _evidence_storage() -> EncryptedObjectStorage:
    key_provider = LocalAesGcmKeyProvider({"test-workflow-evidence-key": b"0" * 32})
    return EncryptedObjectStorage(
        MinioObjectStorage(get_settings()), key_provider, "test-workflow-evidence-key"
    )


async def _activate_trivial_policy(tenant_id: str) -> None:
    """default_outcome-only: no evidence_requirements, no gates, no
    rules -- evaluation is deterministic regardless of what evidence (if
    any) the session carries, which is all these workflow-dispatch tests
    need from the Decision Engine side. INCONCLUSIVE, not VERIFIED/
    REJECTED: the policy schema forbids VERIFIED as a default_outcome
    (DEC-5.23's safety constraint -- a policy with no actual gate/rule
    evaluation logic must never be able to positively assert VERIFIED by
    default)."""
    async with session_factory() as session:
        policy_service, *_ = _services(session)
        await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-workflow-e2e",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
            default_outcome=DecisionOutcome.INCONCLUSIVE,
        )
        await session.commit()


async def _create_session(tenant_id: str) -> UUID:
    async with session_factory() as session:
        _policy_service, session_service, *_ = _services(session)
        created = await session_service.create(
            tenant_id=tenant_id, external_reference=None, assurance_level=AssuranceLevel.STANDARD
        )
        await session.commit()
    return created.id


async def _seed_session_in_status(
    tenant_id: str, status: VerificationStatus, *, expires_at: datetime | None = None
) -> UUID:
    """Directly inserts a row already in the given status, bypassing the
    normal create()/submit() flow -- simulates a session an EARLIER,
    already-interrupted submit() call left behind (crash, timeout), the
    exact precondition §4's PROCESSING-recovery branch exists for."""
    session_id = uuid4()
    async with session_factory() as db_session:
        policy_service, *_ = _services(db_session)
        policy = await policy_service.repository.get_active(
            tenant_id=tenant_id, assurance_level=AssuranceLevel.STANDARD
        )
        assert policy is not None
        now = datetime.now(UTC)
        db_session.add(
            VerificationSessionRecord(
                id=str(session_id),
                tenant_id=tenant_id,
                status=status.value,
                assurance_level="STANDARD",
                created_at=now,
                expires_at=expires_at or (now + timedelta(hours=1)),
                policy_id=policy.policy_id,
                policy_version=policy.version,
                policy_hash=policy.canonical_hash,
                fingerprint="seeded-directly-not-a-real-request",
            )
        )
        await db_session.commit()
    return session_id


async def test_submit_full_pipeline_from_created_to_completed() -> None:
    """Policy -> created session -> submit() -> durable COMPLETED session
    with a durable decision, with nothing faked."""
    tenant_id = f"tenant-workflow-e2e-{uuid4()}"
    await _activate_trivial_policy(tenant_id)
    session_id = await _create_session(tenant_id)

    async with session_factory() as db_session:
        *_rest, workflow = _services(db_session)
        result_session, decision = await workflow.submit(session_id=session_id, tenant_id=tenant_id)
        await db_session.commit()

    assert result_session.status is VerificationStatus.COMPLETED
    assert decision.outcome is DecisionOutcome.INCONCLUSIVE
    assert decision.session_id == session_id

    async with session_factory() as verify_session:
        record = await verify_session.get(VerificationSessionRecord, str(session_id))
        assert record is not None
        assert record.status == VerificationStatus.COMPLETED.value
        decision_row = (
            await verify_session.execute(
                select(DecisionRecord).where(DecisionRecord.session_id == str(session_id))
            )
        ).scalar_one()
        assert decision_row.outcome == DecisionOutcome.INCONCLUSIVE.value


async def test_submit_records_the_lifecycle_audit_events_in_order() -> None:
    tenant_id = f"tenant-workflow-audit-{uuid4()}"
    await _activate_trivial_policy(tenant_id)
    session_id = await _create_session(tenant_id)

    async with session_factory() as db_session:
        *_rest, audit_service, workflow = _services(db_session)
        await workflow.submit(session_id=session_id, tenant_id=tenant_id)
        await db_session.commit()

    async with session_factory() as verify_session:
        audit_repo = SqlAlchemyAuditEventRepository(verify_session)
        events = await audit_repo.list_for_session(session_id, tenant_id)
        event_types = [e.event_type for e in events]
        assert event_types == [
            AuditEventType.SESSION_SUBMITTED,
            AuditEventType.SESSION_PROCESSING_STARTED,
            AuditEventType.DECISION_PRODUCED,
            AuditEventType.SESSION_COMPLETED,
        ]


async def test_first_evidence_submission_advances_created_to_capturing() -> None:
    """WF-001 §2: the one automatic transition in the whole lifecycle
    model, proven against real Postgres + MinIO."""
    tenant_id = f"tenant-workflow-capturing-{uuid4()}"
    await _activate_trivial_policy(tenant_id)
    session_id = await _create_session(tenant_id)
    storage = _evidence_storage()

    async with session_factory() as db_session:
        _policy_service, session_service, *_ = _services(db_session)
        evidence_service = EvidenceService(
            SqlAlchemyEvidenceRepository(db_session),
            session_service,
            storage,
            AuditService(SqlAlchemyAuditEventRepository(db_session)),
        )
        await evidence_service.add(
            session_id=session_id,
            tenant_id=tenant_id,
            evidence_type=EvidenceType.SELFIE,
            content=MINIMAL_JPEG_BYTES,
            checksum="checksum-capturing-proof",
            metadata={},
        )
        await db_session.commit()

    async with session_factory() as verify_session:
        record = await verify_session.get(VerificationSessionRecord, str(session_id))
        assert record is not None
        assert record.status == VerificationStatus.CAPTURING.value
        audit_repo = SqlAlchemyAuditEventRepository(verify_session)
        events = await audit_repo.list_for_session(session_id, tenant_id)
        assert AuditEventType.SESSION_CAPTURING_STARTED in [e.event_type for e in events]


async def test_submit_from_processing_recovers_after_a_simulated_crash() -> None:
    """§4: a session found already in PROCESSING, with no decision yet
    persisted, is the exact shape of an interrupted earlier submit()
    call. This call must complete it, not treat PROCESSING as illegal or
    as a second initiation point."""
    tenant_id = f"tenant-workflow-recovery-{uuid4()}"
    await _activate_trivial_policy(tenant_id)
    session_id = await _seed_session_in_status(tenant_id, VerificationStatus.PROCESSING)

    async with session_factory() as db_session:
        *_rest, workflow = _services(db_session)
        result_session, decision = await workflow.submit(session_id=session_id, tenant_id=tenant_id)
        await db_session.commit()

    assert result_session.status is VerificationStatus.COMPLETED
    assert decision.evaluation_reason is EvaluationReason.NORMAL
    assert decision.outcome is DecisionOutcome.INCONCLUSIVE
    # NO_MATCHING_RULE (the trivial policy's own default_outcome
    # fallback), distinct from the expiration test's
    # SESSION_EXPIRED_DURING_PROCESSING below -- both produce
    # INCONCLUSIVE, for two different, distinguishable reasons.
    assert EngineReasonCode.NO_MATCHING_RULE.value in decision.reason_codes


async def test_submit_from_processing_past_deadline_produces_inconclusive() -> None:
    """§7: PROCESSING has no EXPIRED edge -- a session past its deadline
    while PROCESSING lands at COMPLETED with an INCONCLUSIVE decision via
    EvaluationReason.EXPIRATION, never transitioned to EXPIRED."""
    tenant_id = f"tenant-workflow-expiry-{uuid4()}"
    await _activate_trivial_policy(tenant_id)
    session_id = await _seed_session_in_status(
        tenant_id,
        VerificationStatus.PROCESSING,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    async with session_factory() as db_session:
        *_rest, workflow = _services(db_session)
        result_session, decision = await workflow.submit(session_id=session_id, tenant_id=tenant_id)
        await db_session.commit()

    assert result_session.status is VerificationStatus.COMPLETED
    assert decision.evaluation_reason is EvaluationReason.EXPIRATION
    assert decision.outcome is DecisionOutcome.INCONCLUSIVE
    assert EngineReasonCode.SESSION_EXPIRED_DURING_PROCESSING.value in decision.reason_codes


async def test_submit_from_completed_is_a_true_idempotent_replay() -> None:
    tenant_id = f"tenant-workflow-replay-{uuid4()}"
    await _activate_trivial_policy(tenant_id)
    session_id = await _create_session(tenant_id)

    async with session_factory() as db_session:
        *_rest, workflow = _services(db_session)
        _first_session, first_decision = await workflow.submit(
            session_id=session_id, tenant_id=tenant_id
        )
        await db_session.commit()

    async with session_factory() as db_session:
        *_rest, workflow = _services(db_session)
        second_session, second_decision = await workflow.submit(
            session_id=session_id, tenant_id=tenant_id
        )
        await db_session.commit()

    assert second_session.status is VerificationStatus.COMPLETED
    assert second_decision.decision_id == first_decision.decision_id

    async with session_factory() as verify_session:
        rows = (
            await verify_session.execute(
                select(DecisionRecord).where(DecisionRecord.session_id == str(session_id))
            )
        ).scalars().all()
        assert len(rows) == 1  # exactly one decision, ever
        audit_repo = SqlAlchemyAuditEventRepository(verify_session)
        events = await audit_repo.list_for_session(session_id, tenant_id)
        completed_events = [e for e in events if e.event_type == AuditEventType.SESSION_COMPLETED]
        assert len(completed_events) == 1  # the replay recorded no second audit


async def test_concurrent_submit_from_created_converges_on_one_decision() -> None:
    """WF-001 §4/§6: two requests racing to submit() the SAME freshly
    created session. Barrier-synchronized like every other genuine race
    this project proves against real Postgres (test_verification_session_
    service.py's CAS test, the WF-003 idempotency race tests): an
    asyncio.Event forces the second attempt's transitions to genuinely
    contend with the first's still-open, uncommitted row lock, rather
    than relying on scheduling luck."""
    tenant_id = f"tenant-workflow-race-{uuid4()}"
    await _activate_trivial_policy(tenant_id)
    session_id = await _create_session(tenant_id)
    first_started = asyncio.Event()

    async def _submit_attempt(*, wait_for_signal: bool, delay_before_commit: float) -> UUID:
        async with session_factory() as db_session:
            *_rest, workflow = _services(db_session)
            if wait_for_signal:
                await first_started.wait()
            try:
                _session, decision = await workflow.submit(
                    session_id=session_id, tenant_id=tenant_id
                )
            finally:
                if not wait_for_signal:
                    first_started.set()
            if delay_before_commit:
                await asyncio.sleep(delay_before_commit)
            await db_session.commit()
            return decision.decision_id

    decision_ids = await asyncio.gather(
        _submit_attempt(wait_for_signal=False, delay_before_commit=0.5),
        _submit_attempt(wait_for_signal=True, delay_before_commit=0.0),
    )

    assert decision_ids[0] == decision_ids[1]

    async with session_factory() as verify_session:
        record = await verify_session.get(VerificationSessionRecord, str(session_id))
        assert record is not None
        assert record.status == VerificationStatus.COMPLETED.value
        rows = (
            await verify_session.execute(
                select(DecisionRecord).where(DecisionRecord.session_id == str(session_id))
            )
        ).scalars().all()
        assert len(rows) == 1  # exactly one decision, despite two full concurrent pipelines
        audit_repo = SqlAlchemyAuditEventRepository(verify_session)
        events = await audit_repo.list_for_session(session_id, tenant_id)
        completed_events = [e for e in events if e.event_type == AuditEventType.SESSION_COMPLETED]
        assert len(completed_events) == 1  # the loser converged, recorded no duplicate audit


async def test_concurrent_cancel_vs_submit_produces_one_db_arbitrated_winner() -> None:
    """WF-HV-007 / WF-006 Finding F: the cancel-vs-processing race was
    previously proven only at the unit level, against a fake repository's
    stage_concurrent_winner() hook (tests/unit/test_verification_workflow.py).
    This is the real thing -- a session genuinely in PROCESSING, one
    coroutine racing workflow.submit() (the full evaluate-then-complete
    pipeline) against another racing session_service.cancel(), barrier-
    synchronized so Postgres's row lock on the CAS UPDATE resolves the
    race, not scheduling luck.

    cancel()'s own pre-check reads the row BEFORE attempting its CAS
    write. If that read lands while the race is still live (winner's
    transaction not yet committed), cancel observes PROCESSING, proceeds
    to its own CAS write, and loses it directly -- ConcurrentTransitionError
    (WF-001 §6: an explicit, client-intent-driven request propagates a
    genuine conflict, never swallows it). If instead cancel's read
    happens to land AFTER the winner has already committed (ordinary
    asyncio/connection-pool scheduling jitter around the barrier, not a
    bug), cancel observes the row already terminal and raises
    SessionAlreadyTerminalError instead, without ever attempting the CAS
    write at all. Both are correct, legitimate manifestations of "cancel
    lost the race" -- the test accepts either rather than over-specifying
    an exact exception type that depends on scheduling, not correctness.
    submit()'s own loss is asserted precisely, since its detection path
    doesn't have this same ambiguity: _advance() refetches on a lost CAS
    and re-dispatches, and when that refetch lands on CANCELLED, submit()
    falls through to SessionAlreadyTerminalError every time.

    Whichever side wins, the authoritative state must be fully self-
    consistent: exactly one of {COMPLETED-with-one-decision,
    CANCELLED-with-zero-decisions}, never a hybrid, never both, never
    neither.
    """
    tenant_id = f"tenant-hv007-cancel-vs-submit-{uuid4()}"
    await _activate_trivial_policy(tenant_id)
    session_id = await _seed_session_in_status(tenant_id, VerificationStatus.PROCESSING)
    first_started = asyncio.Event()

    async def _submit_attempt(*, wait_for_signal: bool, delay_before_commit: float) -> str:
        async with session_factory() as db_session:
            *_rest, workflow = _services(db_session)
            if wait_for_signal:
                await first_started.wait()
            try:
                try:
                    await workflow.submit(session_id=session_id, tenant_id=tenant_id)
                except SessionAlreadyTerminalError:
                    await db_session.rollback()
                    return "submit_lost_already_terminal"
            finally:
                if not wait_for_signal:
                    first_started.set()
            if delay_before_commit:
                await asyncio.sleep(delay_before_commit)
            await db_session.commit()
            return "submit_won"

    async def _cancel_attempt(*, wait_for_signal: bool, delay_before_commit: float) -> str:
        async with session_factory() as db_session:
            _policy_service, session_service, *_rest = _services(db_session)
            if wait_for_signal:
                await first_started.wait()
            try:
                try:
                    await session_service.cancel(session_id=session_id, tenant_id=tenant_id)
                except SessionAlreadyTerminalError:
                    await db_session.rollback()
                    return "cancel_lost_already_terminal"
                except ConcurrentTransitionError:
                    await db_session.rollback()
                    return "cancel_lost_concurrent_conflict"
            finally:
                if not wait_for_signal:
                    first_started.set()
            if delay_before_commit:
                await asyncio.sleep(delay_before_commit)
            await db_session.commit()
            return "cancel_won"

    results = await asyncio.gather(
        _submit_attempt(wait_for_signal=False, delay_before_commit=0.5),
        _cancel_attempt(wait_for_signal=True, delay_before_commit=0.0),
    )

    # Exactly one side actually won -- never both, never neither.
    winners = [r for r in results if r.endswith("_won")]
    assert len(winners) == 1

    async with session_factory() as verify_session:
        record = await verify_session.get(VerificationSessionRecord, str(session_id))
        assert record is not None
        decision_rows = (
            await verify_session.execute(
                select(DecisionRecord).where(DecisionRecord.session_id == str(session_id))
            )
        ).scalars().all()

        if winners == ["submit_won"]:
            assert record.status == VerificationStatus.COMPLETED.value
            assert len(decision_rows) == 1
            assert results[1] in (
                "cancel_lost_concurrent_conflict",
                "cancel_lost_already_terminal",
            )
        else:
            assert winners == ["cancel_won"]
            assert record.status == VerificationStatus.CANCELLED.value
            # No decision survives: either evaluate_and_persist() never
            # ran before submit()'s own losing CAS attempt, or it did and
            # the whole attempt (decision INSERT included) rolled back
            # with the rest of that losing transaction -- either way, a
            # cancelled session has zero decisions, never an orphaned one.
            assert decision_rows == []
            assert results[0] == "submit_lost_already_terminal"


async def test_concurrent_cancel_wins_against_a_racing_submit() -> None:
    """The mirror of the test above -- there, submit's own CAS write
    acquires the row lock first (cancel is signaled only after submit's
    full workflow.submit() call returns, then blocks on that lock until
    submit commits), so submit deterministically wins. Here the roles are
    swapped: cancel acquires the row lock first and holds it across a
    delay, submit is signaled only after cancel's own cancel() call
    returns and then blocks on cancel's lock. Both directions of this
    race need their own proof -- a CAS mechanism that only works when
    request A happens to start before request B is not actually safe."""
    tenant_id = f"tenant-hv007-cancel-wins-{uuid4()}"
    await _activate_trivial_policy(tenant_id)
    session_id = await _seed_session_in_status(tenant_id, VerificationStatus.PROCESSING)
    first_started = asyncio.Event()

    async def _cancel_attempt(*, wait_for_signal: bool, delay_before_commit: float) -> str:
        async with session_factory() as db_session:
            _policy_service, session_service, *_rest = _services(db_session)
            if wait_for_signal:
                await first_started.wait()
            try:
                try:
                    await session_service.cancel(session_id=session_id, tenant_id=tenant_id)
                except SessionAlreadyTerminalError:
                    await db_session.rollback()
                    return "cancel_lost_already_terminal"
                except ConcurrentTransitionError:
                    await db_session.rollback()
                    return "cancel_lost_concurrent_conflict"
            finally:
                if not wait_for_signal:
                    first_started.set()
            if delay_before_commit:
                await asyncio.sleep(delay_before_commit)
            await db_session.commit()
            return "cancel_won"

    async def _submit_attempt(*, wait_for_signal: bool, delay_before_commit: float) -> str:
        async with session_factory() as db_session:
            *_rest, workflow = _services(db_session)
            if wait_for_signal:
                await first_started.wait()
            try:
                try:
                    await workflow.submit(session_id=session_id, tenant_id=tenant_id)
                except SessionAlreadyTerminalError:
                    await db_session.rollback()
                    return "submit_lost_already_terminal"
            finally:
                if not wait_for_signal:
                    first_started.set()
            if delay_before_commit:
                await asyncio.sleep(delay_before_commit)
            await db_session.commit()
            return "submit_won"

    results = await asyncio.gather(
        _cancel_attempt(wait_for_signal=False, delay_before_commit=0.5),
        _submit_attempt(wait_for_signal=True, delay_before_commit=0.0),
    )

    winners = [r for r in results if r.endswith("_won")]
    assert winners == ["cancel_won"]  # this ordering makes cancel deterministically win
    assert results[1] == "submit_lost_already_terminal"

    async with session_factory() as verify_session:
        record = await verify_session.get(VerificationSessionRecord, str(session_id))
        assert record is not None
        assert record.status == VerificationStatus.CANCELLED.value
        decision_rows = (
            await verify_session.execute(
                select(DecisionRecord).where(DecisionRecord.session_id == str(session_id))
            )
        ).scalars().all()
        # The critical property this direction specifically proves: a
        # submit() that started evaluating BEFORE losing the race must
        # not let its work leak through as an orphaned decision once
        # cancellation has won -- the losing transaction's staged
        # decision INSERT (if evaluate_and_persist() reached that far
        # before the CAS loss) is discarded with the rest of that
        # rolled-back attempt.
        assert decision_rows == []


async def test_five_way_concurrent_recovery_on_one_stuck_processing_session() -> None:
    """WF-HV-007: generalizes the existing 2-caller concurrent-submit
    test to five, using asyncio.Barrier for genuine N-way overlap (not
    just "two of five happen to overlap") -- the shape of GET's own
    PROCESSING-recovery trigger (WF-006 Finding A) hammered by multiple
    simultaneous pollers, all discovering the same stuck session at once.
    Unlike the cancel-vs-submit races above, every caller here is
    attempting the identical operation, so _advance()'s refetch-and-
    redispatch loop routes every loser through the SAME COMPLETED branch
    the eventual winner reaches -- no caller should see an exception at
    all; all five must converge on the identical decision.
    """
    tenant_id = f"tenant-hv007-five-way-{uuid4()}"
    await _activate_trivial_policy(tenant_id)
    session_id = await _seed_session_in_status(tenant_id, VerificationStatus.PROCESSING)
    caller_count = 5
    barrier = asyncio.Barrier(caller_count)

    async def _recovery_attempt() -> UUID:
        async with session_factory() as db_session:
            *_rest, workflow = _services(db_session)
            await barrier.wait()  # all five reach this point before any proceeds
            _session, decision = await workflow.submit(session_id=session_id, tenant_id=tenant_id)
            await db_session.commit()
            return decision.decision_id

    decision_ids = await asyncio.gather(*(_recovery_attempt() for _ in range(caller_count)))

    assert len(set(decision_ids)) == 1  # every one of the five converged on the same decision

    async with session_factory() as verify_session:
        record = await verify_session.get(VerificationSessionRecord, str(session_id))
        assert record is not None
        assert record.status == VerificationStatus.COMPLETED.value
        decision_rows = (
            await verify_session.execute(
                select(DecisionRecord).where(DecisionRecord.session_id == str(session_id))
            )
        ).scalars().all()
        assert len(decision_rows) == 1  # exactly one, despite five full concurrent pipelines
        audit_repo = SqlAlchemyAuditEventRepository(verify_session)
        events = await audit_repo.list_for_session(session_id, tenant_id)
        completed_events = [e for e in events if e.event_type == AuditEventType.SESSION_COMPLETED]
        assert len(completed_events) == 1  # the four losers converged, recorded no duplicate audit
        produced_events = [
            e for e in events if e.event_type == AuditEventType.DECISION_PRODUCED
        ]
        assert len(produced_events) == 1  # same property, one layer down in the decision domain


async def test_in_flight_submit_beats_a_concurrent_lazy_expiration_read() -> None:
    """WF-HV-008: attacks read-time lazy expiration racing an operation
    already underway -- the specific case named as most likely to hide a
    subtle bug. A session sits in SUBMITTED with expires_at set to fire
    in the immediate future. One coroutine calls workflow.submit()
    (which reads the session, still sees SUBMITTED-and-not-yet-expired,
    and attempts the SUBMITTED->PROCESSING CAS write) and holds its
    transaction open past the deadline. A second, genuinely concurrent
    caller calls session_service.get() -- exactly what a GET request's
    lazy expire_if_needed() does -- after the deadline has passed in
    wall-clock time.

    The wall clock alone would say "this session is expired." The
    invariant under test is that the database, not the clock, is the
    final arbiter: get()'s own lazy-expire CAS write must block on
    submit()'s still-open row lock, and once submit() commits (winning),
    get()'s blocked write finds zero rows affected, catches its own
    ConcurrentTransitionError internally (the same harmless-lost-race
    swallow VerificationSessionService.get() already performs for any
    lost expire race), and returns the CURRENT truth -- PROCESSING, then
    eventually COMPLETED -- never incorrectly stamping an
    already-progressing session as EXPIRED out from under it.
    """
    tenant_id = f"tenant-hv008-submit-beats-expiry-{uuid4()}"
    await _activate_trivial_policy(tenant_id)
    deadline = datetime.now(UTC) + timedelta(milliseconds=150)
    session_id = await _seed_session_in_status(
        tenant_id, VerificationStatus.SUBMITTED, expires_at=deadline
    )
    submit_read_done = asyncio.Event()

    async def _submit_attempt() -> str:
        async with session_factory() as db_session:
            *_rest, workflow = _services(db_session)
            # No wait: starts immediately, while expires_at is still in
            # the future, so its OWN internal get() sees SUBMITTED and
            # not-yet-expired -- exactly the state a real client's
            # /submit call would observe if it beat the deadline by a
            # hair.
            _session, decision = await workflow.submit(
                session_id=session_id, tenant_id=tenant_id
            )
            submit_read_done.set()
            # Held open well past the deadline -- this is the window the
            # concurrent lazy-expire read races into.
            await asyncio.sleep(0.4)
            await db_session.commit()
            return "submit_won"

    async def _lazy_expire_get_attempt() -> str:
        async with session_factory() as db_session:
            _policy_service, session_service, *_rest = _services(db_session)
            await submit_read_done.wait()
            # No wall-clock sanity assertion here: on a fast local
            # Postgres, submit()'s entire internal pipeline (multiple
            # reads, evaluate, persist, two CAS writes) can occasionally
            # complete in under the deadline's own window, so "has the
            # deadline definitely passed yet" is itself racy to assert on
            # -- and unnecessary, since the barrier-sync above already
            # guarantees this read races submit()'s still-open
            # transaction regardless. Found via a 25-iteration stress
            # sweep (one hit) before removing; not a production issue,
            # purely an over-strict test-harness assertion.
            result = await session_service.get(session_id=session_id, tenant_id=tenant_id)
            await db_session.commit()
            return result.status.value

    submit_result, get_result = await asyncio.gather(
        _submit_attempt(), _lazy_expire_get_attempt()
    )

    assert submit_result == "submit_won"
    # A deny-list, deliberately, not an allow-list: this specific
    # invariant ("the database, not the clock, decided") is precisely
    # "never EXPIRED here," not "must be exactly one enumerated value."
    # Found via stress-testing (twice, in this same test) that SUBMITTED
    # is also a legitimate outcome -- if get()'s own read happens to land
    # before both submit()'s commit AND wall-clock expires_at, it
    # correctly returns the still-current SUBMITTED value with no CAS
    # attempt at all, which is exactly what a real GET should do and is
    # not a weaker proof of the property under test.
    assert get_result != "EXPIRED"

    async with session_factory() as verify_session:
        record = await verify_session.get(VerificationSessionRecord, str(session_id))
        assert record is not None
        assert record.status == VerificationStatus.COMPLETED.value
        decision_rows = (
            await verify_session.execute(
                select(DecisionRecord).where(DecisionRecord.session_id == str(session_id))
            )
        ).scalars().all()
        assert len(decision_rows) == 1  # a real decision, not an expiration bypass


async def test_lazy_expiration_beats_an_in_flight_submit() -> None:
    """The mirror direction: the lazy-expire read wins the row lock
    first (holding it across a delay), and a concurrent submit() racing
    in for the SAME SUBMITTED->PROCESSING transition loses. submit()
    must never fabricate PROCESSING (or a decision) on a session that
    just became EXPIRED out from under it -- it has to detect the loss
    and raise, exactly as it does losing to a concurrent cancellation.
    """
    tenant_id = f"tenant-hv008-expiry-beats-submit-{uuid4()}"
    await _activate_trivial_policy(tenant_id)
    deadline = datetime.now(UTC) + timedelta(milliseconds=100)
    session_id = await _seed_session_in_status(
        tenant_id, VerificationStatus.SUBMITTED, expires_at=deadline
    )
    expire_read_done = asyncio.Event()

    async def _lazy_expire_get_attempt() -> str:
        async with session_factory() as db_session:
            _policy_service, session_service, *_rest = _services(db_session)
            await asyncio.sleep(0.15)  # ensures wall-clock time is past the deadline
            result = await session_service.get(session_id=session_id, tenant_id=tenant_id)
            expire_read_done.set()
            await asyncio.sleep(0.3)  # holds the row lock well past submit()'s own read
            await db_session.commit()
            return result.status.value

    async def _submit_attempt() -> str:
        async with session_factory() as db_session:
            *_rest, workflow = _services(db_session)
            await expire_read_done.wait()
            try:
                await workflow.submit(session_id=session_id, tenant_id=tenant_id)
            except SessionAlreadyTerminalError:
                await db_session.rollback()
                return "submit_lost_already_terminal"
            except ConcurrentTransitionError:
                await db_session.rollback()
                return "submit_lost_concurrent_conflict"
            await db_session.commit()
            return "submit_won"

    get_result, submit_result = await asyncio.gather(
        _lazy_expire_get_attempt(), _submit_attempt()
    )

    assert get_result == "EXPIRED"
    # submit()'s own initial read happens after expire's CAS write has
    # already landed (or is landing) -- either detection path is a
    # legitimate "lost to expiration" outcome, mirroring WF-HV-007's own
    # cancel-vs-submit finding that the loser's exact exception type
    # depends on scheduling, not correctness.
    assert submit_result in ("submit_lost_already_terminal", "submit_lost_concurrent_conflict")

    async with session_factory() as verify_session:
        record = await verify_session.get(VerificationSessionRecord, str(session_id))
        assert record is not None
        assert record.status == VerificationStatus.EXPIRED.value
        decision_rows = (
            await verify_session.execute(
                select(DecisionRecord).where(DecisionRecord.session_id == str(session_id))
            )
        ).scalars().all()
        assert decision_rows == []  # EXPIRED never carries a decision, ever
