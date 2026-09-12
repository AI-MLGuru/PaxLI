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
from core.evidence.enums import EvidenceType
from core.evidence.service import EvidenceService
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.evidence_result.service import EvidenceResultService
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel, VerificationStatus
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
        SqlAlchemyVerificationSessionRepository(session), policy_service, session_ttl_minutes=30
    )
    evidence_result_service = EvidenceResultService(
        SqlAlchemyEvidenceResultRepository(session, _KEY_PROVIDER, "test-workflow-key"),
        AuditService(SqlAlchemyAuditEventRepository(session)),
    )
    audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
    persistence_service = DecisionPersistenceService(
        SqlAlchemyDecisionRepository(session), audit_service
    )
    orchestrator = DecisionOrchestrator(
        session_service, policy_service, evidence_result_service, persistence_service, audit_service
    )
    workflow = VerificationWorkflowService(session_service, orchestrator, audit_service)
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
