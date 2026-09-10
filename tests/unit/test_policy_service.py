from datetime import datetime
from uuid import UUID

import pytest

from core.audit.models import AuditEvent
from core.audit.service import AuditService
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.policy.condition import EvidenceCondition
from core.policy.enums import PolicyStatus
from core.policy.exceptions import InvalidPolicyError, PolicyVersionNotFoundError
from core.policy.models import VerificationPolicy
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel


class FakePolicyRepository:
    """In-memory -- proves the service never issues a generic update, only
    `add` and the narrow `mark_superseded` transition."""

    def __init__(self) -> None:
        self.records: dict[UUID, VerificationPolicy] = {}
        self.add_calls = 0
        self.mark_superseded_calls = 0

    async def add(self, policy: VerificationPolicy) -> VerificationPolicy:
        self.add_calls += 1
        self.records[policy.id] = policy
        return policy

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
