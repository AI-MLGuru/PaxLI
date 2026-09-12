"""WF-HV-009: the integrity/checksum attack that found a genuine gap.

EvidenceResult.result is encrypted at rest with AES-256-GCM (an
authenticated cipher) for HIGHLY_SENSITIVE evidence_types, so ciphertext
tampering is cryptographically guaranteed to be detected -- decryption
raises rather than silently returning wrong plaintext (EVD-3.9.3: "An
integrity mismatch MUST NOT silently produce trusted evidence").

Confirmed live before this phase's fix: DecisionOrchestrator.
evaluate_and_persist() read effective evidence outside its own
try/except scope (the same gap WF-006 Finding E named for the policy
read), so the KeyProviderError from a genuinely corrupted
result_ciphertext propagated straight out, uncaught. Via the real HTTP
path that becomes a safe-but-unresolved 500 (WF-006's catch-all) -- safe
against a *transient* DB blip, but this corruption is *permanent*: every
retry hits the identical failure forever, and the session never reaches
any terminal decision at all, contradicting EVD-3.9.4 ("Integrity
failure affecting decision-relevant evidence MUST produce a safe
non-verifying outcome such as INCONCLUSIVE").

Fixed by catching exactly this read (and the symmetric policy-read case,
covered by test_decision_submit_failure_injection.py) and resolving it
to a persisted INCONCLUSIVE decision with EngineReasonCode.
EVIDENCE_UNAVAILABLE, the same DEC-5.24/DEC-5.24.3 safe-failure posture
already used for POLICY_VERSION_UNAVAILABLE and DECISION_ENGINE_ERROR.

Skipped when Postgres isn't reachable, mirroring
tests/integration/test_decision_orchestration_adversarial.py.
"""

import socket
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from sqlalchemy import text

from apps.api.paxli_api.config import get_settings
from core.audit.service import AuditService
from core.decision.enums import DecisionOutcome, EngineReasonCode
from core.decision.orchestration import DecisionOrchestrator
from core.decision.persistence import DecisionPersistenceService
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.evidence_result.service import EvidenceResultService
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel
from core.verification.service import VerificationSessionService
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


async def test_corrupted_evidence_ciphertext_resolves_to_inconclusive_not_a_stuck_session() -> None:
    """The live attack: a real HIGHLY_SENSITIVE FACE_EMBEDDING result is
    created (genuinely encrypted, real AES-GCM round trip), then its
    result_ciphertext is corrupted directly in Postgres -- the exact
    shape of bit-rot, storage corruption, or unauthorized direct-DB
    tampering, not a simulated/mocked failure. Evaluation must neither
    crash uncaught nor fabricate VERIFIED/REJECTED; it must resolve to
    exactly one persisted INCONCLUSIVE decision."""
    tenant_id = f"tenant-hv009-corrupt-{uuid4()}"
    key_provider = LocalAesGcmKeyProvider({"test-hv009-integrity-key": b"0" * 32})
    key_id = "test-hv009-integrity-key"

    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-hv009-corrupt",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
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
            SqlAlchemyEvidenceResultRepository(session, key_provider, key_id),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        victim = await evidence_result_service.create(
            tenant_id=tenant_id,
            session_id=created_session.id,
            evidence_type=EvidenceResultType.FACE_EMBEDDING,
            status=EvidenceResultStatus.PASS,
            producer="face-embedder",
            producer_version="1.0",
            result={"embedding": [0.1, 0.2, 0.3], "embedding_dimensions": 3},
        )
        await session.commit()

    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE evidence_results SET result_ciphertext = "
                "result_ciphertext || :garbage WHERE id = :id"
            ),
            {"garbage": b"CORRUPTED", "id": str(victim.id)},
        )
        await session.commit()

    async with session_factory() as session:
        orchestrator = _orchestrator(session, key_provider, key_id)
        provenance = await orchestrator.evaluate_and_persist(
            session_id=created_session.id, tenant_id=tenant_id
        )
        await session.commit()

    assert provenance.outcome == DecisionOutcome.INCONCLUSIVE
    assert EngineReasonCode.EVIDENCE_UNAVAILABLE.value in provenance.reason_codes

    # Durable and singular: exactly one decision, never VERIFIED/REJECTED.
    async with session_factory() as session:
        decision_repo = SqlAlchemyDecisionRepository(session)
        persisted = await decision_repo.get_for_session(created_session.id, tenant_id)
        assert persisted is not None
        assert persisted.outcome == DecisionOutcome.INCONCLUSIVE

    # Idempotent replay, still corrupted: converges on the SAME decision,
    # never a second attempt and never a different outcome (DEC-5.24.1 /
    # DE-003 "exactly one DecisionResult, once, ever, per session").
    async with session_factory() as session:
        orchestrator = _orchestrator(session, key_provider, key_id)
        replay = await orchestrator.evaluate_and_persist(
            session_id=created_session.id, tenant_id=tenant_id
        )
        await session.commit()
    assert replay.decision_id == provenance.decision_id
