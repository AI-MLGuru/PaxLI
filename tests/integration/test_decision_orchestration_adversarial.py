"""DE-004 Phase 5: hostile conformance tests against real infrastructure.

Not new functionality -- an attempt to falsify DE-003/DE-004 properties
that Phases 1-4's own test suites did not directly exercise at the
orchestrator level. Each test names the DE-003 §16 property (or the new
mutation-after-evaluation class) it targets. See
docs/decisions/DE-004-PHASE-5-CONFORMANCE.md for the full traceability
matrix, including properties already proven elsewhere and cited rather than
duplicated here.
"""

import socket
from urllib.parse import urlparse
from uuid import uuid4

import pytest

from apps.api.paxli_api.config import get_settings
from core.audit.service import AuditService
from core.decision.enums import DecisionOutcome, EngineReasonCode
from core.decision.orchestration import DecisionOrchestrator
from core.decision.persistence import DecisionPersistenceService
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.exceptions import InvalidEvidenceResultError
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


def _face_match_verifies_policy(policy_id: str):
    return dict(
        policy_id=policy_id,
        assurance_level=AssuranceLevel.STANDARD,
        created_by="admin",
        evidence_requirements=(
            EvidenceRequirement(
                evidence_type="FACE_MATCH", level=EvidenceRequirementLevel.REQUIRED
            ),
        ),
        rules=(
            Rule(
                id="r-pass",
                condition=EvidenceCondition(
                    evidence_type="FACE_MATCH", field="status", operator="==", expected_value="PASS"
                ),
                outcome=DecisionOutcome.VERIFIED,
                priority=10,
                reason_code="POLICY:FACE_MATCH_OK",
            ),
            Rule(
                id="r-fail",
                condition=EvidenceCondition(
                    evidence_type="FACE_MATCH", field="status", operator="==", expected_value="FAIL"
                ),
                outcome=DecisionOutcome.REJECTED,
                priority=20,
                reason_code="POLICY:FACE_MATCH_FAILED",
            ),
        ),
    )


async def test_superseded_stale_rejection_does_not_affect_a_verified_outcome() -> None:
    """DE-003 §16 property 15 / adversarial matrix "Superseded evidence":
    excluded from effective evidence, lineage preserved. Attacks the
    orchestrator specifically, not just the resolver in isolation -- a
    stale FaceMatch=FAIL is superseded by FaceMatch=PASS; the orchestrator
    must see only the superseding row."""
    tenant_id = f"tenant-adversarial-supersede-{uuid4()}"
    key_provider = LocalAesGcmKeyProvider({"test-adversarial-key": b"0" * 32})

    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        await policy_service.create_and_activate(
            tenant_id=tenant_id, **_face_match_verifies_policy("policy-adversarial-supersede")
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
            SqlAlchemyEvidenceResultRepository(session, key_provider, "test-adversarial-key"),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        stale_failure = await evidence_result_service.create(
            tenant_id=tenant_id,
            session_id=created_session.id,
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.FAIL,
            producer="face-provider",
            producer_version="1.0",
        )
        await evidence_result_service.supersede(
            evidence_result_id=stale_failure.id,
            tenant_id=tenant_id,
            session_id=created_session.id,
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="2.0",
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
        evidence_result_service = EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(session, key_provider, "test-adversarial-key"),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        orchestrator = DecisionOrchestrator(
            session_service,
            policy_service,
            evidence_result_service,
            DecisionPersistenceService(SqlAlchemyDecisionRepository(session), audit_service),
            audit_service,
        )
        decision = await orchestrator.evaluate_and_persist(
            session_id=created_session.id, tenant_id=tenant_id
        )
        await session.commit()

    # Not REJECTED (which the stale FAIL would have produced) -- VERIFIED,
    # proving the orchestrator's evidence resolution used only the
    # superseding row.
    assert decision.outcome is DecisionOutcome.VERIFIED
    assert decision.reason_codes == ("POLICY:FACE_MATCH_OK",)
    assert len(decision.evidence_references) == 1
    assert decision.evidence_references[0].status == "PASS"


async def test_mutation_between_evaluation_and_persistence_never_taints_the_decision() -> None:
    """The mutation-after-evaluation class: the candidate is computed from
    a frozen snapshot (DecisionEvaluationContext), and nothing that happens
    to the underlying rows after that snapshot was taken can retroactively
    change what gets persisted. Proven here by mutating the real database
    row in the actual gap between evaluate() and persist() -- not merely
    asserted from the pure evaluator's type signature."""
    tenant_id = f"tenant-adversarial-mutation-{uuid4()}"
    key_provider = LocalAesGcmKeyProvider({"test-adversarial-key": b"0" * 32})

    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        await policy_service.create_and_activate(
            tenant_id=tenant_id, **_face_match_verifies_policy("policy-adversarial-mutation")
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
            SqlAlchemyEvidenceResultRepository(session, key_provider, "test-adversarial-key"),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        original_pass = await evidence_result_service.create(
            tenant_id=tenant_id,
            session_id=created_session.id,
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
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
        evidence_result_service = EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(session, key_provider, "test-adversarial-key"),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        persistence_service = DecisionPersistenceService(
            SqlAlchemyDecisionRepository(session), audit_service
        )

        # Reproduce evaluate_and_persist()'s own context-assembly steps by
        # hand, so a real mutation can be inserted in the actual gap
        # between "evidence resolved" and "persisted" -- not simulated.
        fetched_session = await session_service.get(
            session_id=created_session.id, tenant_id=tenant_id
        )
        resolved_policy = await policy_service.get_version(
            policy_id=fetched_session.policy_id,
            version=fetched_session.policy_version,
            tenant_id=tenant_id,
        )
        effective_evidence = await evidence_result_service.list_effective_for_session(
            session_id=created_session.id, tenant_id=tenant_id
        )
        assert {e.id for e in effective_evidence} == {original_pass.id}

        from core.decision.context import DecisionEvaluationContext
        from core.decision.evaluator import evaluate

        context = DecisionEvaluationContext(
            session_id=created_session.id,
            tenant_id=tenant_id,
            policy=resolved_policy,
            effective_evidence=tuple(effective_evidence),
        )
        candidate = evaluate(context)
        assert candidate.outcome is DecisionOutcome.VERIFIED

        # THE ATTACK: mutate the real row in the gap. A concurrent process
        # supersedes the very evidence just evaluated with a FAILING result,
        # in the SAME transaction, before persist() ever runs.
        await evidence_result_service.supersede(
            evidence_result_id=original_pass.id,
            tenant_id=tenant_id,
            session_id=created_session.id,
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.FAIL,
            producer="face-provider",
            producer_version="2.0",
        )

        # persist() the candidate that was ALREADY computed, before the
        # mutation above
        saved = await persistence_service.persist(candidate)
        await session.commit()

    # The persisted decision reflects what was actually evaluated -- VERIFIED,
    # referencing the ORIGINAL (now-superseded) evidence row -- never the
    # FAIL that superseded it moments later.
    assert saved.outcome is DecisionOutcome.VERIFIED
    assert len(saved.evidence_references) == 1
    assert saved.evidence_references[0].evidence_result_id == original_pass.id
    assert saved.evidence_references[0].status == "PASS"

    async with session_factory() as verify_session:
        row = await verify_session.get(DecisionRecord, str(saved.decision_id))
        assert row is not None
        assert row.outcome == "VERIFIED"


async def test_malformed_evidence_submission_never_reaches_the_evaluator() -> None:
    """DE-003 §16 adversarial matrix: "Malformed evidence result -- rejected
    before persistence, never reaches engine." Proves the full chain: a
    payload that fails schema validation is never persisted, so it can
    never appear in list_effective_for_session(), so a required-evidence
    policy sees it as simply absent -- REQUIRED_EVIDENCE_MISSING, never a
    decision computed from corrupted data."""
    tenant_id = f"tenant-adversarial-malformed-{uuid4()}"
    key_provider = LocalAesGcmKeyProvider({"test-adversarial-key": b"0" * 32})

    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        await policy_service.create_and_activate(
            tenant_id=tenant_id, **_face_match_verifies_policy("policy-adversarial-malformed")
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
            SqlAlchemyEvidenceResultRepository(session, key_provider, "test-adversarial-key"),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        with pytest.raises(InvalidEvidenceResultError):
            await evidence_result_service.create(
                tenant_id=tenant_id,
                session_id=created_session.id,
                evidence_type=EvidenceResultType.FACE_MATCH,
                status=EvidenceResultStatus.PASS,
                producer="face-provider",
                producer_version="1.0",
                result={"wrong_field_entirely": "not a similarity score"},
            )
        await session.rollback()

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
        evidence_result_service = EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(session, key_provider, "test-adversarial-key"),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        orchestrator = DecisionOrchestrator(
            session_service,
            policy_service,
            evidence_result_service,
            DecisionPersistenceService(SqlAlchemyDecisionRepository(session), audit_service),
            audit_service,
        )
        decision = await orchestrator.evaluate_and_persist(
            session_id=created_session.id, tenant_id=tenant_id
        )
        await session.commit()

    assert decision.outcome is DecisionOutcome.INCONCLUSIVE
    assert decision.reason_codes == (EngineReasonCode.REQUIRED_EVIDENCE_MISSING.value,)
    assert decision.evidence_references == ()
