"""Real PostgreSQL integration tests for DE-004 Phase 4's evaluation
orchestration boundary -- the full pipeline, end to end, against real
infrastructure: activate a policy, create a session (pinning it), submit
evidence, run the orchestrator, and verify the persisted decision. Skipped
when Postgres isn't reachable, mirroring
tests/integration/test_decision_persistence.py.
"""

import socket
from urllib.parse import urlparse
from uuid import uuid4

import pytest

from apps.api.paxli_api.config import get_settings
from core.audit.service import AuditService
from core.decision.enums import DecisionOutcome, EngineReasonCode, EvaluationReason
from core.decision.orchestration import DecisionOrchestrator
from core.decision.persistence import DecisionPersistenceService
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.evidence_result.service import EvidenceResultService
from core.policy.condition import EvidenceCondition
from core.policy.requirements import EvidenceRequirement, EvidenceRequirementLevel
from core.policy.rules import Rule
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel
from core.verification.service import VerificationSessionService
from infrastructure.database.models.decision import DecisionRecord
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


def _orchestrator(session, key_provider, key_id) -> DecisionOrchestrator:
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
        SqlAlchemyEvidenceResultRepository(session, key_provider, key_id),
        AuditService(SqlAlchemyAuditEventRepository(session)),
        SqlAlchemyEvidenceRepository(session),
    )
    audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
    persistence_service = DecisionPersistenceService(
        SqlAlchemyDecisionRepository(session), audit_service
    )
    return DecisionOrchestrator(
        session_service, policy_service, evidence_result_service, persistence_service, audit_service
    )


async def test_full_pipeline_verified_outcome_against_real_infrastructure() -> None:
    """Policy -> pinned session -> submitted evidence -> orchestrator ->
    durable decision, with nothing faked."""
    tenant_id = f"tenant-orchestration-{uuid4()}"
    key_provider = LocalAesGcmKeyProvider({"test-orchestration-key": b"0" * 32})

    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        policy = await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-orchestration-e2e",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
            evidence_requirements=(
                EvidenceRequirement(
                    evidence_type="FACE_MATCH", level=EvidenceRequirementLevel.REQUIRED
                ),
            ),
            rules=(
                Rule(
                    id="r1",
                    condition=EvidenceCondition(
                        evidence_type="FACE_MATCH",
                        field="status",
                        operator="==",
                        expected_value="PASS",
                    ),
                    outcome=DecisionOutcome.VERIFIED,
                    priority=10,
                    reason_code="POLICY:FACE_MATCH_OK",
                ),
            ),
        )
        await session.commit()

    async with session_factory() as session:
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
        created_session = await session_service.create(
            tenant_id=tenant_id, external_reference=None, assurance_level=AssuranceLevel.STANDARD
        )
        await session.commit()

    assert created_session.policy_id == policy.policy_id
    assert created_session.policy_version == policy.version

    async with session_factory() as session:
        evidence_result_service = EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(session, key_provider, "test-orchestration-key"),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        # BD-001.5 H.2: FaceMatchResult now requires real reference/probe
        # role ids, each a genuine parent -- two minimal embedding rows
        # first, so the FACE_MATCH row below satisfies both the schema
        # and the envelope-boundary provenance check.
        reference_embedding = await evidence_result_service.create(
            tenant_id=tenant_id,
            session_id=created_session.id,
            evidence_type=EvidenceResultType.FACE_EMBEDDING_REFERENCE,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
            result={"embedding": [0.1, 0.2, 0.3], "embedding_dimensions": 3},
        )
        probe_embedding = await evidence_result_service.create(
            tenant_id=tenant_id,
            session_id=created_session.id,
            evidence_type=EvidenceResultType.FACE_EMBEDDING_PROBE,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
            result={"embedding": [0.4, 0.5, 0.6], "embedding_dimensions": 3},
        )
        await evidence_result_service.create(
            tenant_id=tenant_id,
            session_id=created_session.id,
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
            result={
                "similarity": 0.95,
                "reference_evidence_result_id": str(reference_embedding.id),
                "probe_evidence_result_id": str(probe_embedding.id),
            },
            score=0.95,
            parent_evidence_result_ids=(reference_embedding.id, probe_embedding.id),
        )
        await session.commit()

    async with session_factory() as session:
        orchestrator = _orchestrator(session, key_provider, "test-orchestration-key")
        decision = await orchestrator.evaluate_and_persist(
            session_id=created_session.id, tenant_id=tenant_id
        )
        await session.commit()

    assert decision.outcome is DecisionOutcome.VERIFIED
    assert decision.reason_codes == ("POLICY:FACE_MATCH_OK",)
    assert decision.policy_reference.policy_id == policy.policy_id
    assert decision.policy_reference.policy_version == policy.version
    assert decision.policy_reference.policy_hash == policy.canonical_hash
    # bit-for-bit: Decision.policy_reference == Session.policy_reference
    assert decision.policy_reference.policy_id == created_session.policy_id
    assert decision.policy_reference.policy_version == created_session.policy_version
    assert decision.policy_reference.policy_hash == created_session.policy_hash

    async with session_factory() as verify_session:
        row = await verify_session.get(DecisionRecord, str(decision.decision_id))
        assert row is not None
        assert row.outcome == "VERIFIED"

        audit_rows = await SqlAlchemyAuditEventRepository(verify_session).list_for_session(
            created_session.id, tenant_id
        )
        produced = [e for e in audit_rows if e.event_type.value == "DECISION_PRODUCED"]
        assert len(produced) == 1


async def test_persisted_decisions_evidence_reference_integrity_differs_by_score() -> None:
    """WF-HV-009 integrity/checksum: the unit-level tests in
    test_evidence_result_service.py prove _compute_integrity_reference()
    itself is score/quality-sensitive; this proves that sensitivity
    survives the FULL real-infrastructure pipeline into the persisted
    decision's own provenance snapshot (DecisionProvenance.
    evidence_references[*].integrity_reference), not just the
    in-memory EvidenceResult object create() returns. Two sessions,
    identical policy/status/result, differing only in score -- their
    persisted decisions' evidence_references must NOT share an
    integrity_reference."""
    tenant_id = f"tenant-orchestration-integrity-{uuid4()}"
    key_provider = LocalAesGcmKeyProvider({"test-orchestration-key": b"0" * 32})

    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-orchestration-integrity",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
            evidence_requirements=(
                EvidenceRequirement(
                    evidence_type="FACE_MATCH", level=EvidenceRequirementLevel.REQUIRED
                ),
            ),
            rules=(
                Rule(
                    id="r1",
                    condition=EvidenceCondition(
                        evidence_type="FACE_MATCH",
                        field="status",
                        operator="==",
                        expected_value="PASS",
                    ),
                    outcome=DecisionOutcome.VERIFIED,
                    priority=10,
                    reason_code="POLICY:FACE_MATCH_OK",
                ),
            ),
        )
        await session.commit()

    async def _decide_with_score(score: float):
        async with session_factory() as session:
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
            created_session = await session_service.create(
                tenant_id=tenant_id,
                external_reference=None,
                assurance_level=AssuranceLevel.STANDARD,
            )
            await session.commit()

        async with session_factory() as session:
            evidence_result_service = EvidenceResultService(
                SqlAlchemyEvidenceResultRepository(session, key_provider, "test-orchestration-key"),
                AuditService(SqlAlchemyAuditEventRepository(session)),
                SqlAlchemyEvidenceRepository(session),
            )
            await evidence_result_service.create(
                tenant_id=tenant_id,
                session_id=created_session.id,
                evidence_type=EvidenceResultType.FACE_MATCH,
                status=EvidenceResultStatus.PASS,
                producer="face-provider",
                producer_version="1.0",
                score=score,
            )
            await session.commit()

        async with session_factory() as session:
            orchestrator = _orchestrator(session, key_provider, "test-orchestration-key")
            decision = await orchestrator.evaluate_and_persist(
                session_id=created_session.id, tenant_id=tenant_id
            )
            await session.commit()
        return decision

    low_score_decision = await _decide_with_score(0.4)
    high_score_decision = await _decide_with_score(0.99)

    assert len(low_score_decision.evidence_references) == 1
    assert len(high_score_decision.evidence_references) == 1
    assert (
        low_score_decision.evidence_references[0].integrity_reference
        != high_score_decision.evidence_references[0].integrity_reference
    )

    # And it's durable, not just an in-memory artifact of this call.
    async with session_factory() as verify_session:
        persisted_low = await SqlAlchemyDecisionRepository(verify_session).get(
            low_score_decision.decision_id, tenant_id
        )
        persisted_high = await SqlAlchemyDecisionRepository(verify_session).get(
            high_score_decision.decision_id, tenant_id
        )
        assert persisted_low is not None
        assert persisted_high is not None
        assert (
            persisted_low.evidence_references[0].integrity_reference
            != persisted_high.evidence_references[0].integrity_reference
        )


async def test_expiration_short_circuits_to_inconclusive_against_real_infrastructure() -> None:
    """Evidence that would otherwise VERIFY is present, but
    evaluation_reason=EXPIRATION must still produce INCONCLUSIVE
    unconditionally (WF-4.6), proven with a real session/policy/evidence
    row, not a fake."""
    tenant_id = f"tenant-orchestration-expiry-{uuid4()}"
    key_provider = LocalAesGcmKeyProvider({"test-orchestration-key": b"0" * 32})

    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-orchestration-expiry",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
            evidence_requirements=(
                EvidenceRequirement(
                    evidence_type="FACE_MATCH", level=EvidenceRequirementLevel.REQUIRED
                ),
            ),
            rules=(
                Rule(
                    id="r1",
                    condition=EvidenceCondition(
                        evidence_type="FACE_MATCH",
                        field="status",
                        operator="==",
                        expected_value="PASS",
                    ),
                    outcome=DecisionOutcome.VERIFIED,
                    priority=10,
                    reason_code="POLICY:FACE_MATCH_OK",
                ),
            ),
        )
        session_service = VerificationSessionService(
            SqlAlchemyVerificationSessionRepository(session),
            audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
            policy_service=policy_service,
            session_ttl_minutes=30,
        )
        created_session = await session_service.create(
            tenant_id=tenant_id, external_reference=None, assurance_level=AssuranceLevel.STANDARD
        )
        await session.commit()

    async with session_factory() as session:
        evidence_result_service = EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(session, key_provider, "test-orchestration-key"),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        await evidence_result_service.create(
            tenant_id=tenant_id,
            session_id=created_session.id,
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
        )
        await session.commit()

    async with session_factory() as session:
        orchestrator = _orchestrator(session, key_provider, "test-orchestration-key")
        decision = await orchestrator.evaluate_and_persist(
            session_id=created_session.id,
            tenant_id=tenant_id,
            evaluation_reason=EvaluationReason.EXPIRATION,
        )
        await session.commit()

    assert decision.outcome is DecisionOutcome.INCONCLUSIVE
    assert decision.reason_codes == (EngineReasonCode.SESSION_EXPIRED_DURING_PROCESSING.value,)
