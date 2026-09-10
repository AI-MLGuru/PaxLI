from uuid import UUID, uuid4

import pytest

from core.audit.models import AuditEvent
from core.audit.service import AuditService
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.exceptions import InvalidEvidenceResultError
from core.evidence_result.models import EvidenceResult
from core.evidence_result.service import EvidenceResultService


class FakeEvidenceResultRepository:
    """In-memory, insert-only -- proves the service never needs (and the
    Protocol never offers) an update path."""

    def __init__(self) -> None:
        self.records: dict[UUID, EvidenceResult] = {}
        self.add_calls = 0

    async def add(self, evidence_result: EvidenceResult) -> EvidenceResult:
        self.add_calls += 1
        self.records[evidence_result.id] = evidence_result
        return evidence_result

    async def get(self, evidence_result_id: UUID, tenant_id: str) -> EvidenceResult | None:
        record = self.records.get(evidence_result_id)
        return record if record and record.tenant_id == tenant_id else None

    async def list_for_session(self, session_id: UUID, tenant_id: str) -> list[EvidenceResult]:
        return [
            r
            for r in self.records.values()
            if r.session_id == session_id and r.tenant_id == tenant_id
        ]

    async def list_for_session_by_type(
        self, session_id: UUID, tenant_id: str, evidence_type: EvidenceResultType
    ) -> list[EvidenceResult]:
        return [
            r
            for r in await self.list_for_session(session_id, tenant_id)
            if r.evidence_type == evidence_type
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
        return [e for e in self.events if e.session_id == session_id and e.tenant_id == tenant_id]


@pytest.fixture
def service() -> tuple[EvidenceResultService, FakeEvidenceResultRepository, FakeAuditRepository]:
    repo = FakeEvidenceResultRepository()
    audit_repo = FakeAuditRepository()
    return EvidenceResultService(repo, AuditService(audit_repo)), repo, audit_repo


@pytest.mark.asyncio
async def test_create_persists_and_audits(service) -> None:
    svc, repo, audit_repo = service
    session_id = uuid4()

    result = await svc.create(
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
        result={"similarity": 0.91},
        score=0.91,
    )

    assert repo.records[result.id] == result
    assert len(audit_repo.events) == 1
    assert audit_repo.events[0].event_type.value == "EVIDENCE_RESULT_CREATED"
    assert audit_repo.events[0].metadata["evidence_result_id"] == str(result.id)
    assert "result" not in audit_repo.events[0].metadata  # payload never enters audit


@pytest.mark.asyncio
async def test_invalid_result_payload_persists_nothing_and_audits_nothing(service) -> None:
    svc, repo, audit_repo = service

    with pytest.raises(InvalidEvidenceResultError):
        await svc.create(
            tenant_id="tenant-a",
            session_id=uuid4(),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0.0",
            result={"wrong_field": "not what FaceMatch expects"},
        )

    assert repo.add_calls == 0
    assert len(audit_repo.events) == 0


@pytest.mark.asyncio
async def test_supersede_creates_a_new_row_and_never_mutates_the_original(service) -> None:
    svc, repo, _audit_repo = service
    session_id = uuid4()

    original = await svc.create(
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.INCONCLUSIVE,
        producer="face-provider",
        producer_version="1.0.0",
    )
    superseding = await svc.supersede(
        evidence_result_id=original.id,
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.1",
        result={"similarity": 0.95},
        score=0.95,
    )

    assert superseding.id != original.id
    assert superseding.supersedes_id == original.id
    # the original row is untouched -- still INCONCLUSIVE, still in the store
    assert repo.records[original.id].status == EvidenceResultStatus.INCONCLUSIVE
    assert repo.records[original.id].supersedes_id is None
    assert repo.add_calls == 2


@pytest.mark.asyncio
async def test_integrity_reference_is_server_computed_and_deterministic(service) -> None:
    svc, _repo, _audit_repo = service
    session_id = uuid4()

    first = await svc.create(
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
        result={"similarity": 0.5},
    )
    second = await svc.create(
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
        result={"similarity": 0.5},
    )
    # same logical content -> same integrity reference, despite different IDs
    assert first.integrity_reference == second.integrity_reference
    assert first.id != second.id


@pytest.mark.asyncio
async def test_list_for_session_is_tenant_scoped(service) -> None:
    svc, _repo, _audit_repo = service
    session_id = uuid4()
    await svc.create(
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="p",
        producer_version="1",
    )
    await svc.create(
        tenant_id="tenant-b",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="p",
        producer_version="1",
    )

    tenant_a_results = await svc.list_for_session(session_id=session_id, tenant_id="tenant-a")
    assert len(tenant_a_results) == 1
    assert tenant_a_results[0].tenant_id == "tenant-a"
