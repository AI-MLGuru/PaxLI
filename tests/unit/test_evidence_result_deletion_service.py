"""Invariant-06 remediation Phase 3: EvidenceResultService.request_deletion
/ reconcile_deletion -- the analogous lifecycle to
tests/unit/test_evidence_deletion_service.py, applied to an interpreted
result rather than a raw capture."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from core.audit.models import AuditEvent
from core.audit.service import AuditService
from core.deletion.enums import DeletionBasis
from core.deletion.exceptions import (
    DeletionAlreadyRequestedError,
    DeletionBlockedByDependentsError,
    InvalidDeletionRequestError,
)
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.exceptions import EvidenceResultNotFoundError
from core.evidence_result.models import EvidenceResult, EvidenceResultTombstone
from core.evidence_result.service import EvidenceResultService


class FakeEvidenceResultRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, EvidenceResult] = {}
        self.tombstones: dict[UUID, EvidenceResultTombstone] = {}
        self.add_tombstone_calls = 0
        self.blocked_by_dependents = False

    async def add(self, evidence_result: EvidenceResult, idempotency_key: str | None = None):
        self.records[evidence_result.id] = evidence_result
        return evidence_result

    async def get_by_idempotency_key(self, tenant_id, session_id, idempotency_key):
        return None

    async def get(self, evidence_result_id: UUID, tenant_id: str) -> EvidenceResult | None:
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

    async def list_expired(self, tenant_id, as_of):
        return []

    async def has_dependent_evidence_results(
        self, evidence_result_id: UUID, tenant_id: str
    ) -> bool:
        return self.blocked_by_dependents

    async def delete_content(self, evidence_result_id: UUID, tenant_id: str) -> bool:
        record = self.records.get(evidence_result_id)
        if record is None or record.tenant_id != tenant_id:
            return False
        del self.records[evidence_result_id]
        return True

    async def add_tombstone(
        self, tombstone: EvidenceResultTombstone
    ) -> EvidenceResultTombstone:
        self.add_tombstone_calls += 1
        if tombstone.evidence_result_id in self.tombstones:
            raise DeletionAlreadyRequestedError(
                f"a tombstone already exists for "
                f"evidence_result_id={tombstone.evidence_result_id!s}"
            )
        self.tombstones[tombstone.evidence_result_id] = tombstone
        return tombstone

    async def get_tombstone(self, evidence_result_id: UUID, tenant_id: str):
        tombstone = self.tombstones.get(evidence_result_id)
        return tombstone if tombstone and tombstone.tenant_id == tenant_id else None

    async def mark_tombstone_executed(self, evidence_result_id, tenant_id, executed_at):
        tombstone = self.tombstones.get(evidence_result_id)
        if tombstone is None or tombstone.tenant_id != tenant_id:
            raise LookupError("no tombstone")
        updated = tombstone.model_copy(update={"executed_at": executed_at})
        self.tombstones[evidence_result_id] = updated
        return updated


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


class FakeDeletionReconciler:
    def __init__(self, result: EvidenceResultTombstone) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def reconcile(
        self, *, evidence_result_id, tenant_id, request_id=None, correlation_id=None
    ):
        self.calls.append(
            {
                "evidence_result_id": evidence_result_id,
                "tenant_id": tenant_id,
                "request_id": request_id,
                "correlation_id": correlation_id,
            }
        )
        return self.result


def _make_result(tenant_id: str = "tenant-a") -> EvidenceResult:
    return EvidenceResult(
        tenant_id=tenant_id,
        session_id=uuid4(),
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="p",
        producer_version="1",
        integrity_reference="deadbeef",
    )


@pytest.fixture
def service():
    repo = FakeEvidenceResultRepository()
    audit_repo = FakeAuditRepository()
    return EvidenceResultService(repo, AuditService(audit_repo)), repo, audit_repo


@pytest.mark.asyncio
async def test_request_deletion_creates_tombstone_and_audits(service) -> None:
    svc, repo, audit_repo = service
    result = _make_result()
    repo.records[result.id] = result

    tombstone = await svc.request_deletion(
        evidence_result_id=result.id,
        tenant_id="tenant-a",
        deletion_basis=DeletionBasis.DATA_SUBJECT_REQUEST,
        basis_reference=None,
        authorized_by="admin-1",
    )

    assert tombstone.evidence_result_id == result.id
    assert tombstone.executed_at is None
    assert len(audit_repo.events) == 1
    event = audit_repo.events[0]
    assert event.event_type.value == "EVIDENCE_RESULT_DELETION_REQUESTED"
    assert event.metadata["evidence_result_id"] == str(result.id)


@pytest.mark.asyncio
async def test_request_deletion_is_blocked_by_a_dependent_supersession(service) -> None:
    """Phase 6 finding: evidence_results.supersedes_id -> evidence_results.id
    has no ON DELETE behavior, so a request against a result another result
    still supersedes must be rejected before any tombstone or audit event
    is created."""
    svc, repo, audit_repo = service
    result = _make_result()
    repo.records[result.id] = result
    repo.blocked_by_dependents = True

    with pytest.raises(DeletionBlockedByDependentsError):
        await svc.request_deletion(
            evidence_result_id=result.id,
            tenant_id="tenant-a",
            deletion_basis=DeletionBasis.TENANT_REQUEST,
            basis_reference=None,
            authorized_by="admin-1",
        )

    assert repo.tombstones == {}
    assert audit_repo.events == []


@pytest.mark.asyncio
async def test_request_deletion_audit_metadata_never_carries_basis_reference(service) -> None:
    svc, repo, audit_repo = service
    result = _make_result()
    repo.records[result.id] = result

    await svc.request_deletion(
        evidence_result_id=result.id,
        tenant_id="tenant-a",
        deletion_basis=DeletionBasis.OTHER_AUTHORIZED_BASIS,
        basis_reference="confidential-case-reference",
        authorized_by="admin-1",
    )

    assert "basis_reference" not in audit_repo.events[0].metadata
    for value in audit_repo.events[0].metadata.values():
        assert "confidential-case-reference" not in str(value)


@pytest.mark.asyncio
async def test_request_deletion_rejects_invalid_basis_before_any_write(service) -> None:
    svc, repo, audit_repo = service
    result = _make_result()
    repo.records[result.id] = result

    with pytest.raises(InvalidDeletionRequestError):
        await svc.request_deletion(
            evidence_result_id=result.id,
            tenant_id="tenant-a",
            deletion_basis=DeletionBasis.OTHER_AUTHORIZED_BASIS,
            basis_reference=None,
            authorized_by="admin-1",
        )

    assert repo.add_tombstone_calls == 0
    assert len(audit_repo.events) == 0


@pytest.mark.asyncio
async def test_request_deletion_raises_not_found_for_unknown_result(service) -> None:
    svc, _repo, _audit_repo = service
    with pytest.raises(EvidenceResultNotFoundError):
        await svc.request_deletion(
            evidence_result_id=uuid4(),
            tenant_id="tenant-a",
            deletion_basis=DeletionBasis.TENANT_REQUEST,
            basis_reference=None,
            authorized_by="admin-1",
        )


@pytest.mark.asyncio
async def test_request_deletion_is_idempotent_on_replay(service) -> None:
    svc, repo, audit_repo = service
    result = _make_result()
    repo.records[result.id] = result

    first = await svc.request_deletion(
        evidence_result_id=result.id,
        tenant_id="tenant-a",
        deletion_basis=DeletionBasis.TENANT_REQUEST,
        basis_reference=None,
        authorized_by="admin-1",
    )
    second = await svc.request_deletion(
        evidence_result_id=result.id,
        tenant_id="tenant-a",
        deletion_basis=DeletionBasis.RETENTION_EXPIRY,
        basis_reference=None,
        authorized_by="system",
    )

    assert first == second
    assert repo.add_tombstone_calls == 1
    assert len(audit_repo.events) == 1


@pytest.mark.asyncio
async def test_reconcile_deletion_without_configured_reconciler_raises(service) -> None:
    svc, _repo, _audit_repo = service
    with pytest.raises(RuntimeError, match="deletion_reconciler"):
        await svc.reconcile_deletion(evidence_result_id=uuid4(), tenant_id="tenant-a")


@pytest.mark.asyncio
async def test_reconcile_deletion_delegates_to_configured_reconciler(service) -> None:
    svc, _repo, _audit_repo = service
    evidence_result_id = uuid4()
    expected = EvidenceResultTombstone(
        evidence_result_id=evidence_result_id,
        session_id=uuid4(),
        tenant_id="tenant-a",
        deletion_basis=DeletionBasis.TENANT_REQUEST,
        authorized_by="admin-1",
        executed_at=datetime.now(UTC),
        evidence_integrity_reference="deadbeef",
    )
    reconciler = FakeDeletionReconciler(expected)
    svc.deletion_reconciler = reconciler

    result = await svc.reconcile_deletion(
        evidence_result_id=evidence_result_id, tenant_id="tenant-a", request_id="req-1"
    )

    assert result == expected
    assert reconciler.calls == [
        {
            "evidence_result_id": evidence_result_id,
            "tenant_id": "tenant-a",
            "request_id": "req-1",
            "correlation_id": None,
        }
    ]
