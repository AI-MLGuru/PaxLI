"""DE-004 Phase 3: DecisionPersistenceService against in-memory fakes.

Real-Postgres proof of the concurrency/uniqueness/audit-rollback behavior
this service depends on lives in tests/integration/test_decision_persistence.py
-- these tests exercise the service's own logic (which branch it takes, what
it records, what it returns) without needing a database at all.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from core.audit.models import AuditEvent
from core.audit.service import AuditPersistenceError, AuditService
from core.decision.enums import DecisionOutcome, EngineReasonCode, EvaluationReason
from core.decision.exceptions import DecisionAlreadyExistsError
from core.decision.models import DecisionCandidate, DecisionProvenance
from core.decision.persistence import DecisionPersistenceService
from core.decision.references import PolicyReference

TENANT = "tenant-a"
SESSION_ID = uuid4()


def _candidate(*, outcome: DecisionOutcome = DecisionOutcome.INCONCLUSIVE) -> DecisionCandidate:
    return DecisionCandidate(
        session_id=SESSION_ID,
        tenant_id=TENANT,
        outcome=outcome,
        reason_codes=(EngineReasonCode.NO_MATCHING_RULE.value,),
        policy_reference=PolicyReference(
            policy_id="policy-standard", policy_version=1, policy_hash="a" * 64
        ),
        evaluation_reason=EvaluationReason.NORMAL,
    )


class FakeDecisionRepository:
    """In-memory, add-only, keyed by (tenant_id, session_id) -- mirrors the
    real UNIQUE(tenant_id, session_id) constraint's behavior exactly, so
    these tests exercise the same conflict path the real repository does."""

    def __init__(self) -> None:
        self.by_id: dict[UUID, DecisionProvenance] = {}
        self.by_session: dict[tuple[str, UUID], DecisionProvenance] = {}
        self.add_calls = 0

    async def add(self, provenance: DecisionProvenance) -> DecisionProvenance:
        self.add_calls += 1
        key = (provenance.tenant_id, provenance.session_id)
        if key in self.by_session:
            raise DecisionAlreadyExistsError(
                f"a decision already exists for tenant={provenance.tenant_id!r} "
                f"session_id={provenance.session_id!s}"
            )
        self.by_id[provenance.decision_id] = provenance
        self.by_session[key] = provenance
        return provenance

    async def get(self, decision_id: UUID, tenant_id: str) -> DecisionProvenance | None:
        record = self.by_id.get(decision_id)
        return record if record and record.tenant_id == tenant_id else None

    async def get_for_session(self, session_id: UUID, tenant_id: str) -> DecisionProvenance | None:
        return self.by_session.get((tenant_id, session_id))


class FakeAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def add(self, event: AuditEvent, dedupe_key: str | None = None) -> AuditEvent:
        self.events.append(event)
        return event

    async def get_by_dedupe_key(self, tenant_id, session_id, dedupe_key):
        return None

    async def list_for_session(self, session_id, tenant_id):
        return [e for e in self.events if e.session_id == session_id and e.tenant_id == tenant_id]


class FailingAuditRepository:
    async def add(self, event: AuditEvent, dedupe_key: str | None = None) -> AuditEvent:
        raise RuntimeError("simulated audit database outage")

    async def get_by_dedupe_key(self, tenant_id, session_id, dedupe_key):
        return None

    async def list_for_session(self, session_id, tenant_id):
        return []


@pytest.fixture
def service():
    repo = FakeDecisionRepository()
    audit_repo = FakeAuditRepository()
    return DecisionPersistenceService(repo, AuditService(audit_repo)), repo, audit_repo


@pytest.mark.asyncio
async def test_persist_saves_and_records_required_audit(service) -> None:
    svc, repo, audit_repo = service
    saved = await svc.persist(_candidate(outcome=DecisionOutcome.REVIEW_REQUIRED))

    assert repo.by_id[saved.decision_id] == saved
    assert repo.add_calls == 1
    assert len(audit_repo.events) == 1
    event = audit_repo.events[0]
    assert event.event_type.value == "DECISION_PRODUCED"
    assert event.metadata["decision_id"] == str(saved.decision_id)
    assert event.metadata["outcome"] == "REVIEW_REQUIRED"
    assert event.metadata["policy_id"] == "policy-standard"
    # never a raw evidence/result payload -- there is none on the candidate
    # to leak, but the metadata must not silently grow to include one later
    assert set(event.metadata) == {
        "decision_id",
        "outcome",
        "reason_codes",
        "policy_id",
        "policy_version",
        "evaluation_reason",
    }


@pytest.mark.asyncio
async def test_persist_assigns_decision_id_and_created_at_the_evaluator_could_not(
    service,
) -> None:
    """The evaluator's DecisionCandidate has neither field (Phase 2:
    non-deterministic, so it must not exist on a pure function's output).
    Persistence is the single place both get assigned."""
    svc, _repo, _audit_repo = service
    before = datetime.now(UTC)
    saved = await svc.persist(_candidate())
    after = datetime.now(UTC)

    assert isinstance(saved.decision_id, UUID)
    assert before <= saved.created_at <= after


@pytest.mark.asyncio
async def test_repeated_persist_of_the_same_session_converges_on_one_row_no_duplicate_audit(
    service,
) -> None:
    """DE-003 §14 step 3, exercised through the repository's exact conflict
    contract rather than a real race: a second persist() for a session that
    already has a decision must not create a second row, and must not
    record a second DECISION_PRODUCED event -- the winner's own event
    already covers it."""
    svc, repo, audit_repo = service
    first = await svc.persist(_candidate(outcome=DecisionOutcome.VERIFIED))
    second = await svc.persist(_candidate(outcome=DecisionOutcome.REJECTED))

    # the loser adopts the winner's row -- its own (different) candidate
    # outcome never becomes durable
    assert second.decision_id == first.decision_id
    assert second.outcome == first.outcome == DecisionOutcome.VERIFIED
    assert repo.add_calls == 2  # both attempts tried; only the first succeeded
    assert len(repo.by_id) == 1
    assert len(audit_repo.events) == 1


@pytest.mark.asyncio
async def test_conflict_with_no_fetchable_winner_reraises_rather_than_fabricating(
    service,
) -> None:
    """The defensive branch: if DecisionAlreadyExistsError fires but the
    winning row is not (yet) visible to this fetch, the service must not
    return None or invent a result -- DEC-5.24.1 forbids masking an
    unresolved state as any decision outcome."""
    svc, repo, _audit_repo = service

    class _NeverVisibleRepository(FakeDecisionRepository):
        async def get_for_session(self, session_id, tenant_id):
            return None

    always_conflicting = _NeverVisibleRepository()
    always_conflicting.by_session[(TENANT, SESSION_ID)] = "sentinel"  # any truthy conflict marker

    svc2 = DecisionPersistenceService(always_conflicting, svc.audit_service)
    with pytest.raises(DecisionAlreadyExistsError):
        await svc2.persist(_candidate())


@pytest.mark.asyncio
async def test_required_audit_failure_propagates_and_leaves_nothing_recorded() -> None:
    """The service records the decision, then the audit write; if the audit
    write raises AuditPersistenceError, that must propagate rather than be
    swallowed -- the caller's transaction boundary (get_db_session in
    production, an explicit rollback in the real-Postgres integration test)
    is what actually undoes the decision row; this test proves the service
    does not catch and hide the failure itself."""
    repo = FakeDecisionRepository()
    svc = DecisionPersistenceService(repo, AuditService(FailingAuditRepository()))

    with pytest.raises(AuditPersistenceError):
        await svc.persist(_candidate())

    # the repository itself did receive the write (a real DB would roll
    # this back at the transaction boundary; this fake has no such
    # boundary, which is exactly why the real-infrastructure proof lives in
    # the integration test, not here)
    assert repo.add_calls == 1


@pytest.mark.asyncio
async def test_get_and_get_for_session_delegate_to_repository(service) -> None:
    svc, _repo, _audit_repo = service
    saved = await svc.persist(_candidate())

    by_id = await svc.get(decision_id=saved.decision_id, tenant_id=TENANT)
    by_session = await svc.get_for_session(session_id=SESSION_ID, tenant_id=TENANT)

    assert by_id == saved
    assert by_session == saved
    assert await svc.get(decision_id=uuid4(), tenant_id=TENANT) is None
    assert await svc.get_for_session(session_id=uuid4(), tenant_id=TENANT) is None
