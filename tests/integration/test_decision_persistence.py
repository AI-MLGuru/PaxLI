"""Real PostgreSQL integration tests for DE-004 Phase 3 (Decision
persistence + audit transaction). Skipped when Postgres isn't reachable,
mirroring tests/integration/test_evidence_result_persistence.py's pattern.
"""

import asyncio
import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from apps.api.paxli_api.config import get_settings
from core.audit.service import AuditService
from core.decision.enums import DecisionOutcome, EngineReasonCode, EvaluationReason
from core.decision.models import DecisionCandidate
from core.decision.persistence import DecisionPersistenceService
from core.decision.references import EvidenceReference, PolicyReference
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.service import EvidenceResultService
from infrastructure.database.models.decision import DecisionRecord
from infrastructure.database.models.evidence_result import EvidenceResultRecord
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.decision import SqlAlchemyDecisionRepository
from infrastructure.database.repositories.evidence_result import SqlAlchemyEvidenceResultRepository
from infrastructure.database.session import session_factory
from infrastructure.security.local_key_provider import LocalAesGcmKeyProvider


def _postgres_reachable() -> bool:
    url = urlparse(get_settings().database_url.replace("+asyncpg", ""))
    try:
        with socket.create_connection((url.hostname, url.port or 5432), timeout=1):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.skipif(not _postgres_reachable(), reason="PostgreSQL is not reachable"),
    pytest.mark.asyncio(loop_scope="module"),
]


@pytest.fixture(scope="module", autouse=True)
async def _dispose_shared_engine_pool_after_module():
    from infrastructure.database.session import engine

    yield
    await engine.dispose()


async def _create_session(session, tenant_id: str) -> str:
    session_id = str(uuid4())
    session.add(
        VerificationSessionRecord(
            id=session_id,
            tenant_id=tenant_id,
            status="CREATED",
            assurance_level="STANDARD",
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await session.flush()
    return session_id


def _candidate(
    *,
    session_id,
    tenant_id: str,
    outcome: DecisionOutcome = DecisionOutcome.INCONCLUSIVE,
    evidence_references: tuple[EvidenceReference, ...] = (),
    policy_id: str = "policy-decision-test",
) -> DecisionCandidate:
    return DecisionCandidate(
        session_id=session_id,
        tenant_id=tenant_id,
        outcome=outcome,
        reason_codes=(EngineReasonCode.NO_MATCHING_RULE.value,),
        policy_reference=PolicyReference(
            policy_id=policy_id, policy_version=1, policy_hash="h" * 64
        ),
        evidence_references=evidence_references,
        evaluation_reason=EvaluationReason.NORMAL,
    )


async def test_add_persists_and_round_trips_through_get_and_get_for_session() -> None:
    tenant_id = "tenant-decision-roundtrip"
    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        repo = SqlAlchemyDecisionRepository(session)
        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        svc = DecisionPersistenceService(repo, audit_service)

        candidate = _candidate(
            session_id=session_id, tenant_id=tenant_id, outcome=DecisionOutcome.VERIFIED
        )
        saved = await svc.persist(candidate)
        await session.commit()

        fetched_by_id = await repo.get(saved.decision_id, tenant_id)
        fetched_by_session = await repo.get_for_session(saved.session_id, tenant_id)
        assert fetched_by_id == saved
        assert fetched_by_session == saved
        assert fetched_by_id.outcome == DecisionOutcome.VERIFIED
        assert fetched_by_id.policy_reference.policy_id == "policy-decision-test"

        # cross-tenant lookups see nothing
        assert await repo.get(saved.decision_id, "tenant-other") is None
        assert await repo.get_for_session(saved.session_id, "tenant-other") is None


async def test_unique_constraint_rejects_second_decision_for_same_session_direct_insert() -> None:
    """Direct proof against real PostgreSQL that
    uq_decisions_tenant_session is enforced at the database level -- two
    independent DecisionRecord rows for the same (tenant_id, session_id)
    cannot both be inserted, regardless of application logic."""
    async with session_factory() as session:
        tenant_id = "tenant-decision-unique-index-test"
        session_id = await _create_session(session, tenant_id)
        common = {
            "tenant_id": tenant_id,
            "session_id": session_id,
            "outcome": "INCONCLUSIVE",
            "reason_codes_json": [EngineReasonCode.NO_MATCHING_RULE.value],
            "policy_id": "policy-x",
            "policy_version": 1,
            "policy_hash": "h" * 64,
            "evidence_references_json": [],
            "model_references_json": [],
            "calibration_references_json": [],
            "prohibited_types_present_json": [],
            "evaluation_reason": "NORMAL",
            "engine_version": "1.0.0",
            "created_at": datetime.now(UTC),
        }
        session.add(DecisionRecord(id=str(uuid4()), **common))
        await session.flush()
        session.add(DecisionRecord(id=str(uuid4()), **common))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_required_audit_failure_leaves_no_decision_row() -> None:
    """Invariant 12 / DE-003 §14 step 4: a required-audit failure must not
    leave the decision row durably persisted -- same shape as
    test_evidence_result_persistence.py's
    test_required_audit_failure_leaves_no_evidence_result_row."""
    from core.audit.service import AuditPersistenceError

    class FailingAuditEventRepository:
        async def add(self, event, dedupe_key=None):
            raise RuntimeError("simulated audit database outage")

        async def get_by_dedupe_key(self, tenant_id, session_id, dedupe_key):
            return None

        async def list_for_session(self, session_id, tenant_id):
            return []

    async with session_factory() as session:
        tenant_id = "tenant-decision-audit-failure"
        session_id = await _create_session(session, tenant_id)
        repo = SqlAlchemyDecisionRepository(session)
        svc = DecisionPersistenceService(repo, AuditService(FailingAuditEventRepository()))

        with pytest.raises(AuditPersistenceError):
            await svc.persist(_candidate(session_id=session_id, tenant_id=tenant_id))
        await session.rollback()

    async with session_factory() as verify_session:
        result = await verify_session.execute(
            select(DecisionRecord).where(
                DecisionRecord.tenant_id == "tenant-decision-audit-failure"
            )
        )
        assert result.scalars().all() == []


async def test_decision_survives_hard_deletion_of_the_evidence_it_referenced() -> None:
    """DE-002 landmine 1 / DE-003 §12, proved against real infrastructure,
    not just asserted by schema shape: hard-deleting the EvidenceResult row
    a decision's evidence_references snapshot points to must not alter,
    orphan-cascade, or block either row. There is no FK to violate and no
    row to keep alive -- the snapshot is the historical record."""
    tenant_id = "tenant-decision-soft-reference"
    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        key_provider = LocalAesGcmKeyProvider({"test-decision-evidence-key": b"0" * 32})
        evidence_repo = SqlAlchemyEvidenceResultRepository(
            session, key_provider, "test-decision-evidence-key"
        )
        evidence_service = EvidenceResultService(
            evidence_repo, AuditService(SqlAlchemyAuditEventRepository(session))
        )
        evidence = await evidence_service.create(
            tenant_id=tenant_id,
            session_id=session_id,
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
            result={"similarity": 0.91},
            score=0.91,
        )
        decision_repo = SqlAlchemyDecisionRepository(session)
        decision_service = DecisionPersistenceService(
            decision_repo, AuditService(SqlAlchemyAuditEventRepository(session))
        )
        candidate = _candidate(
            session_id=session_id,
            tenant_id=tenant_id,
            outcome=DecisionOutcome.VERIFIED,
            evidence_references=(EvidenceReference.from_evidence_result(evidence),),
        )
        saved = await decision_service.persist(candidate)
        await session.commit()

    # Hard-delete the evidence content row, in a fresh session -- the exact
    # same repository call Invariant-06 remediation's reconciliation phase
    # uses in production.
    async with session_factory() as session:
        deleted = await SqlAlchemyEvidenceResultRepository(
            session, key_provider, "test-decision-evidence-key"
        ).delete_content(evidence.id, tenant_id)
        await session.commit()
    assert deleted is True

    async with session_factory() as verify_session:
        evidence_row = await verify_session.get(EvidenceResultRecord, str(evidence.id))
        assert evidence_row is None  # genuinely gone, not soft-deleted

        decision_row = await SqlAlchemyDecisionRepository(verify_session).get(
            saved.decision_id, tenant_id
        )
        assert decision_row is not None
        assert decision_row.outcome == DecisionOutcome.VERIFIED
        # the snapshot survives untouched, orphaned reference and all
        assert len(decision_row.evidence_references) == 1
        reference = decision_row.evidence_references[0]
        assert reference.evidence_result_id == evidence.id
        assert reference.evidence_type == "FACE_MATCH"
        assert reference.status == "PASS"
        assert reference.integrity_reference == evidence.integrity_reference


async def test_concurrent_persist_for_the_same_session_converges_on_exactly_one_decision() -> None:
    """DE-003 §16 property 6: two concurrent evaluations of the same
    session produce exactly one DecisionResult row; the loser observes the
    winner's.

    Uses the same barrier-synchronized methodology as
    test_policy_persistence.py's
    test_concurrent_activation_for_the_same_applicability_one_wins_one_conflicts
    -- a plain asyncio.gather is not reliable proof by itself (a fast local
    Postgres can let one coroutine finish before the other's first await is
    scheduled), so an asyncio.Event forces genuine transaction overlap.
    Unlike that test, this service's own conflict-recovery path (a
    SAVEPOINT inside SqlAlchemyDecisionRepository.add -- see its docstring)
    means the losing side never needs to roll back and retry manually: its
    own persist() call resolves the conflict internally and returns the
    winner's row.
    """
    async with session_factory() as setup_session:
        tenant_id = "tenant-decision-race"
        session_id = await _create_session(setup_session, tenant_id)
        await setup_session.commit()

    first_persisted = asyncio.Event()

    async def _attempt(outcome: DecisionOutcome, *, wait_for_signal: bool, delay: float):
        async with session_factory() as session:
            repo = SqlAlchemyDecisionRepository(session)
            audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
            svc = DecisionPersistenceService(repo, audit_service)
            candidate = _candidate(session_id=session_id, tenant_id=tenant_id, outcome=outcome)

            if wait_for_signal:
                await first_persisted.wait()
            try:
                result = await svc.persist(candidate)
            finally:
                if not wait_for_signal:
                    first_persisted.set()
            if delay:
                await asyncio.sleep(delay)
            await session.commit()
            return result

    results = await asyncio.gather(
        _attempt(DecisionOutcome.VERIFIED, wait_for_signal=False, delay=0.5),
        _attempt(DecisionOutcome.REJECTED, wait_for_signal=True, delay=0.0),
    )

    first_result, second_result = results
    # both calls converge on the SAME row -- the loser's own candidate
    # (REJECTED) never becomes durable
    assert first_result.decision_id == second_result.decision_id
    assert first_result.outcome == second_result.outcome == DecisionOutcome.VERIFIED

    async with session_factory() as verify_session:
        rows = (
            (
                await verify_session.execute(
                    select(DecisionRecord).where(
                        DecisionRecord.tenant_id == tenant_id,
                        DecisionRecord.session_id == session_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

        audit_rows = await SqlAlchemyAuditEventRepository(verify_session).list_for_session(
            first_result.session_id, tenant_id
        )
        produced = [e for e in audit_rows if e.event_type.value == "DECISION_PRODUCED"]
        assert len(produced) == 1  # the loser never recorded a second one
