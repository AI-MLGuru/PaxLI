"""Invariant-06 remediation Phase 3: EvidenceService.request_deletion /
reconcile_deletion. Fakes only -- the atomicity/rollback proof for a
required-audit failure belongs at the integration level against real
Postgres (tests/integration/test_evidence_deletion_service.py), the same
split Invariant-12 remediation already established for evidence results.
"""

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
from core.evidence.enums import EvidenceSource, EvidenceType
from core.evidence.models import Evidence, EvidenceTombstone
from core.evidence.service import EvidenceNotFoundError, EvidenceService
from core.verification.service import VerificationSessionService


class FakeEvidenceRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, Evidence] = {}
        self.tombstones: dict[UUID, EvidenceTombstone] = {}
        self.add_tombstone_calls = 0
        self.blocked_by_dependents = False

    async def add(self, evidence: Evidence, idempotency_key: str | None = None) -> Evidence:
        self.records[evidence.id] = evidence
        return evidence

    async def get_by_idempotency_key(self, tenant_id, session_id, idempotency_key):
        return None

    async def get(self, evidence_id: UUID, tenant_id: str) -> Evidence | None:
        record = self.records.get(evidence_id)
        return record if record and record.tenant_id == tenant_id else None

    async def list_for_session(self, session_id, tenant_id):
        return [
            r
            for r in self.records.values()
            if r.session_id == session_id and r.tenant_id == tenant_id
        ]

    async def list_expired(self, tenant_id, as_of):
        return []

    async def has_dependent_evidence_results(self, evidence_id: UUID, tenant_id: str) -> bool:
        return self.blocked_by_dependents

    async def delete_content(self, evidence_id: UUID, tenant_id: str) -> bool:
        record = self.records.get(evidence_id)
        if record is None or record.tenant_id != tenant_id:
            return False
        del self.records[evidence_id]
        return True

    async def add_tombstone(self, tombstone: EvidenceTombstone) -> EvidenceTombstone:
        self.add_tombstone_calls += 1
        if tombstone.evidence_id in self.tombstones:
            raise DeletionAlreadyRequestedError(
                f"a tombstone already exists for evidence_id={tombstone.evidence_id!s}"
            )
        self.tombstones[tombstone.evidence_id] = tombstone
        return tombstone

    async def get_tombstone(self, evidence_id: UUID, tenant_id: str) -> EvidenceTombstone | None:
        tombstone = self.tombstones.get(evidence_id)
        return tombstone if tombstone and tombstone.tenant_id == tenant_id else None

    async def mark_tombstone_executed(self, evidence_id, tenant_id, executed_at):
        tombstone = self.tombstones.get(evidence_id)
        if tombstone is None or tombstone.tenant_id != tenant_id:
            raise LookupError("no tombstone")
        updated = tombstone.model_copy(update={"executed_at": executed_at})
        self.tombstones[evidence_id] = updated
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


class FakeSessionRepository:
    async def get(self, *args, **kwargs):
        raise NotImplementedError


class FakeDeletionReconciler:
    def __init__(self, result: EvidenceTombstone) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def reconcile(
        self, *, evidence_id, tenant_id, request_id=None, correlation_id=None
    ) -> EvidenceTombstone:
        self.calls.append(
            {
                "evidence_id": evidence_id,
                "tenant_id": tenant_id,
                "request_id": request_id,
                "correlation_id": correlation_id,
            }
        )
        return self.result


def _make_evidence(tenant_id: str = "tenant-a") -> Evidence:
    return Evidence(
        session_id=uuid4(),
        tenant_id=tenant_id,
        evidence_type=EvidenceType.SELFIE,
        source=EvidenceSource.CLIENT,
        object_key=f"{tenant_id}/obj",
        checksum="a" * 64,
        mime_type="image/jpeg",
        size_bytes=10,
    )


@pytest.fixture
def service():
    repo = FakeEvidenceRepository()
    audit_repo = FakeAuditRepository()
    svc = EvidenceService(
        repo,
        VerificationSessionService(FakeSessionRepository(), session_ttl_minutes=60),
        storage=None,  # not exercised by request_deletion/reconcile_deletion
        audit_service=AuditService(audit_repo),
    )
    return svc, repo, audit_repo


@pytest.mark.asyncio
async def test_request_deletion_creates_tombstone_and_audits(service) -> None:
    svc, repo, audit_repo = service
    evidence = _make_evidence()
    repo.records[evidence.id] = evidence

    tombstone = await svc.request_deletion(
        evidence_id=evidence.id,
        tenant_id="tenant-a",
        deletion_basis=DeletionBasis.TENANT_REQUEST,
        basis_reference=None,
        authorized_by="admin-1",
    )

    assert tombstone.evidence_id == evidence.id
    assert tombstone.executed_at is None
    assert len(audit_repo.events) == 1
    event = audit_repo.events[0]
    assert event.event_type.value == "EVIDENCE_DELETION_REQUESTED"
    assert event.metadata["evidence_id"] == str(evidence.id)
    assert event.metadata["deletion_basis"] == "TENANT_REQUEST"


@pytest.mark.asyncio
async def test_request_deletion_is_blocked_by_a_dependent_evidence_result(service) -> None:
    """Phase 6 finding: evidence_results.source_reference -> evidence.id has
    no ON DELETE behavior, so a request against evidence with a dependent
    must be rejected before any tombstone or audit event is created."""
    svc, repo, audit_repo = service
    evidence = _make_evidence()
    repo.records[evidence.id] = evidence
    repo.blocked_by_dependents = True

    with pytest.raises(DeletionBlockedByDependentsError):
        await svc.request_deletion(
            evidence_id=evidence.id,
            tenant_id="tenant-a",
            deletion_basis=DeletionBasis.TENANT_REQUEST,
            basis_reference=None,
            authorized_by="admin-1",
        )

    assert repo.tombstones == {}
    assert audit_repo.events == []


@pytest.mark.asyncio
async def test_request_deletion_audit_metadata_never_carries_basis_reference(service) -> None:
    """Explicit Phase-3 instruction: don't put the deletion basis's
    sensitive underlying material into the audit event."""
    svc, repo, audit_repo = service
    evidence = _make_evidence()
    repo.records[evidence.id] = evidence

    await svc.request_deletion(
        evidence_id=evidence.id,
        tenant_id="tenant-a",
        deletion_basis=DeletionBasis.OTHER_AUTHORIZED_BASIS,
        basis_reference="internal-case-file-12345-confidential",
        authorized_by="admin-1",
    )

    assert "basis_reference" not in audit_repo.events[0].metadata
    for value in audit_repo.events[0].metadata.values():
        assert "internal-case-file" not in str(value)


@pytest.mark.asyncio
async def test_request_deletion_rejects_invalid_basis_before_any_write(service) -> None:
    svc, repo, audit_repo = service
    evidence = _make_evidence()
    repo.records[evidence.id] = evidence

    with pytest.raises(InvalidDeletionRequestError):
        await svc.request_deletion(
            evidence_id=evidence.id,
            tenant_id="tenant-a",
            deletion_basis=DeletionBasis.OTHER_AUTHORIZED_BASIS,
            basis_reference=None,
            authorized_by="admin-1",
        )

    assert repo.add_tombstone_calls == 0
    assert len(audit_repo.events) == 0


@pytest.mark.asyncio
async def test_request_deletion_raises_not_found_for_unknown_evidence(service) -> None:
    svc, _repo, _audit_repo = service
    with pytest.raises(EvidenceNotFoundError):
        await svc.request_deletion(
            evidence_id=uuid4(),
            tenant_id="tenant-a",
            deletion_basis=DeletionBasis.TENANT_REQUEST,
            basis_reference=None,
            authorized_by="admin-1",
        )


@pytest.mark.asyncio
async def test_request_deletion_is_idempotent_on_replay(service) -> None:
    svc, repo, audit_repo = service
    evidence = _make_evidence()
    repo.records[evidence.id] = evidence

    first = await svc.request_deletion(
        evidence_id=evidence.id,
        tenant_id="tenant-a",
        deletion_basis=DeletionBasis.TENANT_REQUEST,
        basis_reference=None,
        authorized_by="admin-1",
    )
    second = await svc.request_deletion(
        evidence_id=evidence.id,
        tenant_id="tenant-a",
        deletion_basis=DeletionBasis.DATA_SUBJECT_REQUEST,  # ignored on replay
        basis_reference=None,
        authorized_by="admin-2",
    )

    assert first == second
    assert repo.add_tombstone_calls == 1
    assert len(audit_repo.events) == 1


@pytest.mark.asyncio
async def test_reconcile_deletion_without_configured_reconciler_raises(service) -> None:
    svc, _repo, _audit_repo = service
    with pytest.raises(RuntimeError, match="deletion_reconciler"):
        await svc.reconcile_deletion(evidence_id=uuid4(), tenant_id="tenant-a")


@pytest.mark.asyncio
async def test_reconcile_deletion_delegates_to_configured_reconciler(service) -> None:
    svc, _repo, _audit_repo = service
    evidence_id = uuid4()
    expected = EvidenceTombstone(
        evidence_id=evidence_id,
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
        evidence_id=evidence_id, tenant_id="tenant-a", request_id="req-1"
    )

    assert result == expected
    assert reconciler.calls == [
        {
            "evidence_id": evidence_id,
            "tenant_id": "tenant-a",
            "request_id": "req-1",
            "correlation_id": None,
        }
    ]
