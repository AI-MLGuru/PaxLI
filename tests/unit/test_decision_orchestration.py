"""DE-004 Phase 4: the evaluation orchestration boundary, against
in-memory fakes. Real-Postgres end-to-end proof (policy -> session ->
evidence -> orchestrator -> persisted decision) lives in
tests/integration/test_decision_orchestration.py.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from core.audit.models import AuditEvent
from core.audit.service import AuditService
from core.decision.enums import DecisionOutcome, EngineReasonCode, EvaluationReason
from core.decision.exceptions import DecisionAlreadyExistsError
from core.decision.models import DecisionProvenance
from core.decision.orchestration import DecisionOrchestrator, SessionHasNoPolicyPinError
from core.decision.persistence import DecisionPersistenceService
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.models import EvidenceResult
from core.evidence_result.service import EvidenceResultService
from core.policy.condition import EvidenceCondition
from core.policy.enums import PolicyStatus
from core.policy.models import VerificationPolicy
from core.policy.requirements import EvidenceRequirement, EvidenceRequirementLevel
from core.policy.rules import Rule
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel, VerificationStatus
from core.verification.models import VerificationSession
from core.verification.service import VerificationSessionService

TENANT = "tenant-a"


# ---------------------------------------------------------------------------
# Fakes -- self-contained, mirroring the shapes already proven in
# test_policy_service.py / test_evidence_result_service.py / test_decision_
# persistence.py / test_verification_session_policy_pinning.py.
# ---------------------------------------------------------------------------


class FakeSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, VerificationSession] = {}

    async def add(self, session, idempotency_key=None):
        self.sessions[session.id] = session
        return session

    async def get(self, session_id, tenant_id):
        session = self.sessions.get(session_id)
        return session if session and session.tenant_id == tenant_id else None

    async def get_by_idempotency_key(self, tenant_id, idempotency_key):
        return None

    async def list(self, tenant_id):
        return [s for s in self.sessions.values() if s.tenant_id == tenant_id]

    async def update(self, session):
        self.sessions[session.id] = session
        return session


class FakePolicyRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, VerificationPolicy] = {}

    async def add(self, policy, idempotency_key=None):
        self.records[policy.id] = policy
        return policy

    async def get_by_idempotency_key(self, tenant_id, idempotency_key):
        return None

    async def mark_superseded(self, policy_row_id, tenant_id, superseded_at):
        record = self.records[policy_row_id]
        self.records[policy_row_id] = record.model_copy(
            update={"status": PolicyStatus.SUPERSEDED, "superseded_at": superseded_at}
        )

    async def get(self, policy_row_id, tenant_id):
        record = self.records.get(policy_row_id)
        return record if record and record.tenant_id == tenant_id else None

    async def get_active(self, tenant_id, assurance_level):
        for record in self.records.values():
            if (
                record.tenant_id == tenant_id
                and record.assurance_level == assurance_level
                and record.status == PolicyStatus.ACTIVE
            ):
                return record
        return None

    async def get_version(self, policy_id, version, tenant_id):
        for record in self.records.values():
            if (
                record.policy_id == policy_id
                and record.version == version
                and record.tenant_id == tenant_id
            ):
                return record
        return None

    async def get_max_version(self, policy_id, tenant_id):
        versions = [
            r.version
            for r in self.records.values()
            if r.policy_id == policy_id and r.tenant_id == tenant_id
        ]
        return max(versions, default=0)

    async def list_versions(self, policy_id, tenant_id):
        return [
            r
            for r in self.records.values()
            if r.policy_id == policy_id and r.tenant_id == tenant_id
        ]


class NullSchemaCatalog:
    def is_known_evidence_type(self, evidence_type: str) -> bool:
        return True

    def supports_field(self, evidence_type: str, field: str) -> bool:
        return True


class FakeEvidenceResultRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, EvidenceResult] = {}
        self.not_effective: set[UUID] = set()

    async def add(self, evidence_result, idempotency_key=None):
        self.records[evidence_result.id] = evidence_result
        return evidence_result

    async def get_by_idempotency_key(self, tenant_id, session_id, idempotency_key):
        return None

    async def get(self, evidence_result_id, tenant_id):
        record = self.records.get(evidence_result_id)
        return record if record and record.tenant_id == tenant_id else None

    async def list_for_session(self, session_id, tenant_id):
        return [
            r
            for r in self.records.values()
            if r.session_id == session_id and r.tenant_id == tenant_id
        ]

    async def list_for_session_by_type(self, session_id, tenant_id, evidence_type):
        return [
            r
            for r in await self.list_for_session(session_id, tenant_id)
            if r.evidence_type == evidence_type
        ]

    async def list_effective_for_session(self, session_id, tenant_id):
        return [
            r
            for r in await self.list_for_session(session_id, tenant_id)
            if r.id not in self.not_effective
        ]

    async def list_effective_for_session_by_type(self, session_id, tenant_id, evidence_type):
        return [
            r
            for r in await self.list_effective_for_session(session_id, tenant_id)
            if r.evidence_type == evidence_type
        ]

    async def mark_not_effective(self, evidence_result_id, tenant_id):
        self.not_effective.add(evidence_result_id)

    async def list_expired(self, tenant_id, as_of):
        return []

    async def has_dependent_evidence_results(self, evidence_result_id, tenant_id):
        return False

    async def delete_content(self, evidence_result_id, tenant_id):
        return bool(self.records.pop(evidence_result_id, None))

    async def add_tombstone(self, tombstone):
        raise NotImplementedError

    async def get_tombstone(self, evidence_result_id, tenant_id):
        return None

    async def mark_tombstone_executed(self, evidence_result_id, tenant_id, executed_at):
        raise NotImplementedError


class FakeDecisionRepository:
    def __init__(self) -> None:
        self.by_id: dict[UUID, DecisionProvenance] = {}
        self.by_session: dict[tuple[str, UUID], DecisionProvenance] = {}

    async def add(self, provenance):
        key = (provenance.tenant_id, provenance.session_id)
        if key in self.by_session:
            raise DecisionAlreadyExistsError("conflict")
        self.by_id[provenance.decision_id] = provenance
        self.by_session[key] = provenance
        return provenance

    async def get(self, decision_id, tenant_id):
        record = self.by_id.get(decision_id)
        return record if record and record.tenant_id == tenant_id else None

    async def get_for_session(self, session_id, tenant_id):
        return self.by_session.get((tenant_id, session_id))


class FakeAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def add(self, event, dedupe_key=None):
        self.events.append(event)
        return event

    async def get_by_dedupe_key(self, tenant_id, session_id, dedupe_key):
        return None

    async def list_for_session(self, session_id, tenant_id):
        return [e for e in self.events if e.session_id == session_id and e.tenant_id == tenant_id]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _session_with_pin(
    *,
    tenant_id: str = TENANT,
    policy_id: str,
    policy_version: int,
    policy_hash: str,
    status: VerificationStatus = VerificationStatus.PROCESSING,
) -> VerificationSession:
    now = datetime.now(UTC)
    return VerificationSession(
        tenant_id=tenant_id,
        status=status,
        assurance_level=AssuranceLevel.STANDARD,
        created_at=now,
        expires_at=now + timedelta(hours=1),
        policy_id=policy_id,
        policy_version=policy_version,
        policy_hash=policy_hash,
    )


def _evidence(
    session_id: UUID,
    *,
    evidence_type: EvidenceResultType = EvidenceResultType.FACE_MATCH,
    status: EvidenceResultStatus = EvidenceResultStatus.PASS,
) -> EvidenceResult:
    return EvidenceResult(
        tenant_id=TENANT,
        session_id=session_id,
        evidence_type=evidence_type,
        status=status,
        producer="p",
        producer_version="1",
        produced_at=datetime.now(UTC),
        persisted_at=datetime.now(UTC),
        integrity_reference="ref",
    )


class _Harness:
    def __init__(self) -> None:
        self.session_repo = FakeSessionRepository()
        self.policy_repo = FakePolicyRepository()
        self.evidence_repo = FakeEvidenceResultRepository()
        self.decision_repo = FakeDecisionRepository()
        self.audit_repo = FakeAuditRepository()

        self.policy_service = PolicyService(
            self.policy_repo, AuditService(FakeAuditRepository()), NullSchemaCatalog()
        )
        self.session_service = VerificationSessionService(
            self.session_repo, self.policy_service, session_ttl_minutes=30
        )
        self.evidence_result_service = EvidenceResultService(
            self.evidence_repo, AuditService(FakeAuditRepository())
        )
        self.audit_service = AuditService(self.audit_repo)
        self.persistence_service = DecisionPersistenceService(
            self.decision_repo, self.audit_service
        )
        self.orchestrator = DecisionOrchestrator(
            self.session_service,
            self.policy_service,
            self.evidence_result_service,
            self.persistence_service,
            self.audit_service,
        )


@pytest.fixture
def harness() -> _Harness:
    return _Harness()


def _matching_policy(**overrides) -> VerificationPolicy:
    defaults = dict(
        id=uuid4(),
        policy_id="policy-orchestration",
        version=1,
        tenant_id=TENANT,
        assurance_level=AssuranceLevel.STANDARD,
        status=PolicyStatus.ACTIVE,
        canonical_hash="hash-v1",
        created_by="admin",
    )
    defaults.update(overrides)
    return VerificationPolicy(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_evaluates_and_persists_using_the_pinned_policy(harness) -> None:
    policy = _matching_policy(
        evidence_requirements=(
            EvidenceRequirement(
                evidence_type="FACE_MATCH", level=EvidenceRequirementLevel.REQUIRED
            ),
        ),
        rules=(
            Rule(
                id="r1",
                condition=EvidenceCondition(
                    evidence_type="FACE_MATCH", field="status", operator="==", expected_value="PASS"
                ),
                outcome=DecisionOutcome.VERIFIED,
                priority=10,
                reason_code="POLICY:FACE_MATCH_OK",
            ),
        ),
    )
    await harness.policy_repo.add(policy)
    session = _session_with_pin(
        policy_id=policy.policy_id, policy_version=policy.version, policy_hash=policy.canonical_hash
    )
    await harness.session_repo.add(session)
    await harness.evidence_repo.add(_evidence(session.id))

    decision = await harness.orchestrator.evaluate_and_persist(
        session_id=session.id, tenant_id=TENANT
    )

    assert decision.outcome is DecisionOutcome.VERIFIED
    assert decision.policy_reference.policy_id == policy.policy_id
    assert decision.policy_reference.policy_hash == policy.canonical_hash
    produced = [e for e in harness.audit_repo.events if e.event_type.value == "DECISION_PRODUCED"]
    assert len(produced) == 1


@pytest.mark.asyncio
async def test_session_with_no_policy_pin_raises_a_precondition_error(harness) -> None:
    now = datetime.now(UTC)
    unpinned = VerificationSession(
        tenant_id=TENANT,
        status=VerificationStatus.PROCESSING,
        assurance_level=AssuranceLevel.STANDARD,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    await harness.session_repo.add(unpinned)

    with pytest.raises(SessionHasNoPolicyPinError):
        await harness.orchestrator.evaluate_and_persist(session_id=unpinned.id, tenant_id=TENANT)


@pytest.mark.asyncio
async def test_unresolvable_pinned_version_produces_policy_version_unavailable(harness) -> None:
    """The pin points to a (policy_id, version) that get_version() cannot
    find -- policies are never deleted, so this signals corruption, not an
    ordinary miss."""
    session = _session_with_pin(policy_id="policy-ghost", policy_version=1, policy_hash="h" * 8)
    await harness.session_repo.add(session)

    decision = await harness.orchestrator.evaluate_and_persist(
        session_id=session.id, tenant_id=TENANT
    )

    assert decision.outcome is DecisionOutcome.INCONCLUSIVE
    assert decision.reason_codes == (EngineReasonCode.POLICY_VERSION_UNAVAILABLE.value,)
    assert decision.policy_reference.policy_id == "policy-ghost"


@pytest.mark.asyncio
async def test_hash_mismatch_against_the_pin_produces_policy_invalid(harness) -> None:
    policy = _matching_policy(canonical_hash="hash-actual")
    await harness.policy_repo.add(policy)
    # the session's pin disagrees with the stored policy's real hash
    session = _session_with_pin(
        policy_id=policy.policy_id, policy_version=policy.version, policy_hash="hash-pinned-wrong"
    )
    await harness.session_repo.add(session)

    decision = await harness.orchestrator.evaluate_and_persist(
        session_id=session.id, tenant_id=TENANT
    )

    assert decision.outcome is DecisionOutcome.INCONCLUSIVE
    assert decision.reason_codes == (EngineReasonCode.POLICY_INVALID.value,)
    # the pin's own (wrong) hash is what's recorded, not the actual stored one
    assert decision.policy_reference.policy_hash == "hash-pinned-wrong"


@pytest.mark.asyncio
async def test_evaluator_exception_produces_decision_engine_error_and_its_own_audit_event(
    harness, monkeypatch
) -> None:
    policy = _matching_policy()
    await harness.policy_repo.add(policy)
    session = _session_with_pin(
        policy_id=policy.policy_id, policy_version=policy.version, policy_hash=policy.canonical_hash
    )
    await harness.session_repo.add(session)

    def _boom(context):
        raise RuntimeError("simulated evaluator crash")

    monkeypatch.setattr("core.decision.orchestration.evaluate", _boom)

    decision = await harness.orchestrator.evaluate_and_persist(
        session_id=session.id, tenant_id=TENANT
    )

    assert decision.outcome is DecisionOutcome.INCONCLUSIVE
    assert decision.reason_codes == (EngineReasonCode.DECISION_ENGINE_ERROR.value,)
    failed = [
        e for e in harness.audit_repo.events if e.event_type.value == "DECISION_ENGINE_FAILED"
    ]
    assert len(failed) == 1
    assert failed[0].status.value == "FAILURE"
    # DECISION_PRODUCED still fires for the resulting INCONCLUSIVE candidate
    produced = [e for e in harness.audit_repo.events if e.event_type.value == "DECISION_PRODUCED"]
    assert len(produced) == 1


@pytest.mark.asyncio
async def test_expiration_reason_passes_through_to_the_evaluator_unconditionally(harness) -> None:
    policy = _matching_policy(
        evidence_requirements=(
            EvidenceRequirement(
                evidence_type="FACE_MATCH", level=EvidenceRequirementLevel.REQUIRED
            ),
        ),
        rules=(
            Rule(
                id="r1",
                condition=EvidenceCondition(
                    evidence_type="FACE_MATCH", field="status", operator="==", expected_value="PASS"
                ),
                outcome=DecisionOutcome.VERIFIED,
                priority=10,
                reason_code="POLICY:FACE_MATCH_OK",
            ),
        ),
    )
    await harness.policy_repo.add(policy)
    session = _session_with_pin(
        policy_id=policy.policy_id, policy_version=policy.version, policy_hash=policy.canonical_hash
    )
    await harness.session_repo.add(session)
    await harness.evidence_repo.add(_evidence(session.id))  # would otherwise VERIFY

    decision = await harness.orchestrator.evaluate_and_persist(
        session_id=session.id, tenant_id=TENANT, evaluation_reason=EvaluationReason.EXPIRATION
    )

    assert decision.outcome is DecisionOutcome.INCONCLUSIVE
    assert decision.reason_codes == (EngineReasonCode.SESSION_EXPIRED_DURING_PROCESSING.value,)


@pytest.mark.asyncio
async def test_reinvoking_for_an_already_decided_session_converges_on_the_same_decision(
    harness,
) -> None:
    policy = _matching_policy(default_outcome=DecisionOutcome.REVIEW_REQUIRED)
    await harness.policy_repo.add(policy)
    session = _session_with_pin(
        policy_id=policy.policy_id, policy_version=policy.version, policy_hash=policy.canonical_hash
    )
    await harness.session_repo.add(session)

    first = await harness.orchestrator.evaluate_and_persist(session_id=session.id, tenant_id=TENANT)
    second = await harness.orchestrator.evaluate_and_persist(
        session_id=session.id, tenant_id=TENANT
    )

    assert second.decision_id == first.decision_id
    produced = [e for e in harness.audit_repo.events if e.event_type.value == "DECISION_PRODUCED"]
    assert len(produced) == 1  # the second call recorded nothing new
