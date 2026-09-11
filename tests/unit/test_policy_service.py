from datetime import datetime
from typing import Any
from uuid import UUID

import pytest

from core.audit.enums import AuditActorType, AuditEventType
from core.audit.models import AuditEvent
from core.audit.service import AuditService
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.policy.condition import EvidenceCondition
from core.policy.enums import PolicyStatus
from core.policy.exceptions import (
    InvalidPolicyError,
    PolicyActivationConflictError,
    PolicyVersionNotFoundError,
)
from core.policy.models import VerificationPolicy
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel


class FakePolicyRepository:
    """In-memory -- proves the service never issues a generic update, only
    `add` and the narrow `mark_superseded` transition."""

    def __init__(self) -> None:
        self.records: dict[UUID, VerificationPolicy] = {}
        self.idempotency_keys: dict[tuple[str, str], UUID] = {}
        self.add_calls = 0
        self.mark_superseded_calls = 0
        self.raise_conflict_on_next_add = False

    async def add(
        self, policy: VerificationPolicy, idempotency_key: str | None = None
    ) -> VerificationPolicy:
        if self.raise_conflict_on_next_add:
            self.raise_conflict_on_next_add = False
            raise PolicyActivationConflictError("simulated concurrent activation conflict")
        self.add_calls += 1
        self.records[policy.id] = policy
        if idempotency_key is not None:
            self.idempotency_keys[(policy.tenant_id, idempotency_key)] = policy.id
        return policy

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> VerificationPolicy | None:
        policy_row_id = self.idempotency_keys.get((tenant_id, idempotency_key))
        return self.records.get(policy_row_id) if policy_row_id is not None else None

    async def mark_superseded(
        self, policy_row_id: UUID, tenant_id: str, superseded_at: datetime
    ) -> None:
        self.mark_superseded_calls += 1
        record = self.records[policy_row_id]
        self.records[policy_row_id] = record.model_copy(
            update={"status": PolicyStatus.SUPERSEDED, "superseded_at": superseded_at}
        )

    async def get(self, policy_row_id: UUID, tenant_id: str) -> VerificationPolicy | None:
        record = self.records.get(policy_row_id)
        return record if record and record.tenant_id == tenant_id else None

    async def get_active(
        self, tenant_id: str, assurance_level: AssuranceLevel
    ) -> VerificationPolicy | None:
        for record in self.records.values():
            if (
                record.tenant_id == tenant_id
                and record.assurance_level == assurance_level
                and record.status == PolicyStatus.ACTIVE
            ):
                return record
        return None

    async def get_version(
        self, policy_id: str, version: int, tenant_id: str
    ) -> VerificationPolicy | None:
        for record in self.records.values():
            if (
                record.policy_id == policy_id
                and record.version == version
                and record.tenant_id == tenant_id
            ):
                return record
        return None

    async def get_max_version(self, policy_id: str, tenant_id: str) -> int:
        versions = [
            r.version
            for r in self.records.values()
            if r.policy_id == policy_id and r.tenant_id == tenant_id
        ]
        return max(versions, default=0)

    async def list_versions(self, policy_id: str, tenant_id: str) -> list[VerificationPolicy]:
        return [
            r
            for r in self.records.values()
            if r.policy_id == policy_id and r.tenant_id == tenant_id
        ]


class FakeAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def add(self, event: AuditEvent, dedupe_key: str | None = None) -> AuditEvent:
        self.events.append(event)
        return event

    async def get_by_dedupe_key(self, tenant_id, session_id, dedupe_key):
        return None

    async def list_for_session(self, session_id, tenant_id):
        return []


class FakeIndependentAuditRecorder:
    """Records calls without touching any session -- proves PolicyService
    calls this on a conflict, with what arguments, independent of whether a
    real independent transaction is actually involved (that guarantee is
    proved separately against real Postgres)."""

    def __init__(self, *, raise_on_record: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.raise_on_record = raise_on_record

    async def record_independently(
        self,
        *,
        tenant_id: str,
        event_type: AuditEventType,
        component: str,
        action: str,
        actor_type: AuditActorType,
        actor_id: str | None,
        request_id: str | None,
        correlation_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        if self.raise_on_record:
            raise RuntimeError("simulated independent audit persistence failure")
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "component": component,
                "action": action,
                "actor_type": actor_type,
                "actor_id": actor_id,
                "metadata": metadata,
            }
        )


@pytest.fixture
def service() -> tuple[PolicyService, FakePolicyRepository, FakeAuditRepository]:
    repo = FakePolicyRepository()
    audit_repo = FakeAuditRepository()
    svc = PolicyService(repo, AuditService(audit_repo), EvidenceResultSchemaCatalog())
    return svc, repo, audit_repo


@pytest.mark.asyncio
async def test_create_and_activate_persists_and_audits(service) -> None:
    svc, repo, audit_repo = service

    policy = await svc.create_and_activate(
        tenant_id="tenant-a",
        policy_id="kyc-standard",
        assurance_level=AssuranceLevel.STANDARD,
        created_by="admin-1",
        thresholds={"pass": 0.9},
    )

    assert policy.status == PolicyStatus.ACTIVE
    assert policy.version == 1
    assert repo.records[policy.id] == policy
    assert len(audit_repo.events) == 1
    event = audit_repo.events[0]
    assert event.event_type.value == "POLICY_ACTIVATED"
    assert event.metadata["activation_type"] == "INITIAL"
    assert event.metadata["policy_id"] == "kyc-standard"
    assert event.metadata["previous_active_policy_id"] is None


@pytest.mark.asyncio
async def test_repeated_idempotency_key_resolves_to_the_same_version_not_a_new_one(
    service,
) -> None:
    """Invariant-12 remediation: a retried activation request must not
    silently create a second real policy version."""
    svc, repo, _ = service

    first = await svc.create_and_activate(
        tenant_id="tenant-a",
        policy_id="kyc-standard",
        assurance_level=AssuranceLevel.STANDARD,
        created_by="admin-1",
        thresholds={"pass": 0.9},
        idempotency_key="req-abc",
    )
    second = await svc.create_and_activate(
        tenant_id="tenant-a",
        policy_id="kyc-standard",
        assurance_level=AssuranceLevel.STANDARD,
        created_by="admin-1",
        thresholds={"pass": 0.9},
        idempotency_key="req-abc",
    )

    assert first.id == second.id
    assert first.version == second.version == 1
    assert repo.add_calls == 1  # only the first call actually persisted anything


@pytest.mark.asyncio
async def test_same_raw_idempotency_key_does_not_collide_across_activate_and_rollback(
    service,
) -> None:
    """The composed key must be operation-scoped: a caller reusing the same
    raw key for create-and-activate and, separately, rollback must not have
    the second call mistaken for a replay of the first (Invariant-12
    remediation review)."""
    svc, _, _ = service

    activated = await svc.create_and_activate(
        tenant_id="tenant-a",
        policy_id="kyc-standard",
        assurance_level=AssuranceLevel.STANDARD,
        created_by="admin-1",
        thresholds={"pass": 0.9},
        idempotency_key="same-raw-key",
    )
    rolled_back = await svc.rollback(
        tenant_id="tenant-a",
        policy_id="kyc-standard",
        target_version=1,
        created_by="admin-1",
        idempotency_key="same-raw-key",
    )

    assert rolled_back.id != activated.id
    assert rolled_back.version == 2


@pytest.mark.asyncio
async def test_invalid_policy_persists_nothing_and_audits_nothing(service) -> None:
    svc, repo, audit_repo = service
    bad_condition = EvidenceCondition(
        evidence_type="FACE_MATCH", field="not_a_real_field", operator="==", expected_value=True
    )

    with pytest.raises(InvalidPolicyError):
        await svc.create_and_activate(
            tenant_id="tenant-a",
            policy_id="kyc-standard",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin-1",
            conditions=bad_condition,
        )

    assert repo.add_calls == 0
    assert repo.mark_superseded_calls == 0
    assert len(audit_repo.events) == 0


@pytest.mark.asyncio
async def test_second_activation_for_same_applicability_supersedes_the_first(service) -> None:
    svc, repo, audit_repo = service

    first = await svc.create_and_activate(
        tenant_id="tenant-a",
        policy_id="kyc-standard",
        assurance_level=AssuranceLevel.STANDARD,
        created_by="admin-1",
    )
    second = await svc.create_and_activate(
        tenant_id="tenant-a",
        policy_id="kyc-standard",
        assurance_level=AssuranceLevel.STANDARD,
        created_by="admin-1",
        thresholds={"pass": 0.99},
    )

    assert repo.records[first.id].status == PolicyStatus.SUPERSEDED
    assert repo.records[first.id].superseded_at is not None
    assert second.status == PolicyStatus.ACTIVE
    assert second.version == 2
    assert second.supersedes_id == first.id
    assert repo.mark_superseded_calls == 1
    assert audit_repo.events[1].metadata["previous_active_policy_id"] == str(first.id)


@pytest.mark.asyncio
async def test_different_assurance_levels_do_not_supersede_each_other(service) -> None:
    svc, repo, _audit_repo = service

    standard = await svc.create_and_activate(
        tenant_id="tenant-a",
        policy_id="kyc-standard",
        assurance_level=AssuranceLevel.STANDARD,
        created_by="admin-1",
    )
    enhanced = await svc.create_and_activate(
        tenant_id="tenant-a",
        policy_id="kyc-enhanced",
        assurance_level=AssuranceLevel.ENHANCED,
        created_by="admin-1",
    )

    assert repo.records[standard.id].status == PolicyStatus.ACTIVE
    assert repo.records[enhanced.id].status == PolicyStatus.ACTIVE
    assert repo.mark_superseded_calls == 0


@pytest.mark.asyncio
async def test_rollback_creates_a_new_version_content_identical_to_the_target(service) -> None:
    svc, repo, audit_repo = service

    v1 = await svc.create_and_activate(
        tenant_id="tenant-a",
        policy_id="kyc-standard",
        assurance_level=AssuranceLevel.STANDARD,
        created_by="admin-1",
        thresholds={"pass": 0.9},
    )
    await svc.create_and_activate(
        tenant_id="tenant-a",
        policy_id="kyc-standard",
        assurance_level=AssuranceLevel.STANDARD,
        created_by="admin-1",
        thresholds={"pass": 0.99},
    )

    v3 = await svc.rollback(
        tenant_id="tenant-a", policy_id="kyc-standard", target_version=1, created_by="admin-2"
    )

    assert v3.id != v1.id
    assert v3.version == 3
    assert v3.canonical_hash == v1.canonical_hash
    assert v3.status == PolicyStatus.ACTIVE
    # v1 is untouched by the rollback -- it was already SUPERSEDED by v2,
    # and remains exactly as it was, never flipped back to ACTIVE.
    stored_v1 = repo.records[v1.id]
    assert stored_v1.status == PolicyStatus.SUPERSEDED
    assert stored_v1.version == 1
    assert stored_v1.canonical_hash == v1.canonical_hash
    assert audit_repo.events[-1].metadata["activation_type"] == "ROLLBACK"
    assert audit_repo.events[-1].metadata["rollback_source_policy_id"] == str(v1.id)


@pytest.mark.asyncio
async def test_rollback_to_a_nonexistent_version_raises(service) -> None:
    svc, _repo, _audit_repo = service
    with pytest.raises(PolicyVersionNotFoundError):
        await svc.rollback(
            tenant_id="tenant-a", policy_id="kyc-standard", target_version=1, created_by="admin-1"
        )


@pytest.mark.asyncio
async def test_activation_conflict_propagates_unmasked_when_no_recorder_configured() -> None:
    """Backward-compatible default: PolicyActivationConflictError still
    propagates untouched when no failure_audit_recorder is supplied (the
    existing 22 tests in this file construct PolicyService this way)."""
    repo = FakePolicyRepository()
    audit_repo = FakeAuditRepository()
    svc = PolicyService(repo, AuditService(audit_repo), EvidenceResultSchemaCatalog())
    repo.raise_conflict_on_next_add = True

    with pytest.raises(PolicyActivationConflictError):
        await svc.create_and_activate(
            tenant_id="tenant-a",
            policy_id="kyc-standard",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin-1",
        )


@pytest.mark.asyncio
async def test_activation_conflict_records_independent_failure_audit() -> None:
    """Invariant-12 remediation 2, Option 2: a genuine activation conflict
    triggers the independent failure-audit recorder with the right
    context, and the original conflict still propagates."""
    repo = FakePolicyRepository()
    audit_repo = FakeAuditRepository()
    recorder = FakeIndependentAuditRecorder()
    svc = PolicyService(
        repo, AuditService(audit_repo), EvidenceResultSchemaCatalog(), recorder
    )
    repo.raise_conflict_on_next_add = True

    with pytest.raises(PolicyActivationConflictError):
        await svc.create_and_activate(
            tenant_id="tenant-a",
            policy_id="kyc-standard",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin-1",
        )

    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["tenant_id"] == "tenant-a"
    assert call["event_type"].value == "POLICY_ACTIVATION_FAILED"
    assert call["actor_id"] == "admin-1"
    assert call["metadata"]["policy_id"] == "kyc-standard"
    # the conflict prevented persistence -- nothing was ever added
    assert repo.add_calls == 0
    # and the normal SUCCESS audit path was never reached either
    assert audit_repo.events == []


@pytest.mark.asyncio
async def test_failure_audit_write_failure_never_masks_the_original_conflict() -> None:
    """Explicit decision (Invariant-12 remediation 2 review): if the
    independent failure-audit write itself fails, the original
    PolicyActivationConflictError must still propagate -- never replaced
    by a fabricated success or a different error type."""
    repo = FakePolicyRepository()
    audit_repo = FakeAuditRepository()
    recorder = FakeIndependentAuditRecorder(raise_on_record=True)
    svc = PolicyService(
        repo, AuditService(audit_repo), EvidenceResultSchemaCatalog(), recorder
    )
    repo.raise_conflict_on_next_add = True

    with pytest.raises(PolicyActivationConflictError):
        await svc.create_and_activate(
            tenant_id="tenant-a",
            policy_id="kyc-standard",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin-1",
        )
