from uuid import UUID, uuid4

import pytest

from core.audit.models import AuditEvent
from core.audit.service import AuditService
from core.evidence.enums import EvidenceSource, EvidenceType
from core.evidence.models import Evidence
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.exceptions import (
    InvalidEvidenceResultError,
    InvalidProvenanceReferenceError,
    InvalidSupersessionError,
)
from core.evidence_result.models import EvidenceResult
from core.evidence_result.service import EvidenceResultService


class FakeEvidenceRepository:
    """Minimal in-memory fake of core.evidence.repository.EvidenceRepository
    -- only get() is exercised by EvidenceResultService's provenance
    validation (WF-HV-009 Finding B); the rest raise NotImplementedError,
    matching this suite's existing fake-repository convention."""

    def __init__(self) -> None:
        self.records: dict[UUID, Evidence] = {}

    async def add(self, evidence: Evidence, idempotency_key: str | None = None) -> Evidence:
        raise NotImplementedError

    async def get_by_idempotency_key(self, tenant_id, session_id, idempotency_key):
        raise NotImplementedError

    async def get(self, evidence_id: UUID, tenant_id: str) -> Evidence | None:
        record = self.records.get(evidence_id)
        return record if record and record.tenant_id == tenant_id else None

    async def list_for_session(self, session_id, tenant_id):
        raise NotImplementedError

    async def list_expired(self, tenant_id, as_of):
        raise NotImplementedError

    async def has_dependent_evidence_results(self, evidence_id, tenant_id):
        raise NotImplementedError

    async def delete_content(self, evidence_id, tenant_id):
        raise NotImplementedError

    async def add_tombstone(self, tombstone):
        raise NotImplementedError

    async def get_tombstone(self, evidence_id, tenant_id):
        raise NotImplementedError

    async def mark_tombstone_executed(self, evidence_id, tenant_id, executed_at):
        raise NotImplementedError


class FakeEvidenceResultRepository:
    """In-memory, insert-only -- proves the service never needs (and the
    Protocol never offers) an update path."""

    def __init__(self) -> None:
        self.records: dict[UUID, EvidenceResult] = {}
        self.idempotency_keys: dict[tuple[str, UUID, str], UUID] = {}
        self.add_calls = 0
        self.not_effective: set[UUID] = set()
        self.mark_not_effective_calls = 0

    async def add(
        self, evidence_result: EvidenceResult, idempotency_key: str | None = None
    ) -> EvidenceResult:
        self.add_calls += 1
        self.records[evidence_result.id] = evidence_result
        if idempotency_key is not None:
            key = (evidence_result.tenant_id, evidence_result.session_id, idempotency_key)
            self.idempotency_keys[key] = evidence_result.id
        return evidence_result

    async def get_by_idempotency_key(
        self, tenant_id: str, session_id: UUID, idempotency_key: str
    ) -> EvidenceResult | None:
        result_id = self.idempotency_keys.get((tenant_id, session_id, idempotency_key))
        return self.records.get(result_id) if result_id is not None else None

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

    async def list_effective_for_session(
        self, session_id: UUID, tenant_id: str
    ) -> list[EvidenceResult]:
        return [
            r
            for r in await self.list_for_session(session_id, tenant_id)
            if r.id not in self.not_effective
        ]

    async def list_effective_for_session_by_type(
        self, session_id: UUID, tenant_id: str, evidence_type: EvidenceResultType
    ) -> list[EvidenceResult]:
        return [
            r
            for r in await self.list_effective_for_session(session_id, tenant_id)
            if r.evidence_type == evidence_type
        ]

    async def mark_not_effective(
        self,
        evidence_result_id: UUID,
        tenant_id: str,
        session_id: UUID,
        evidence_type: EvidenceResultType,
    ) -> bool:
        self.mark_not_effective_calls += 1
        record = self.records.get(evidence_result_id)
        if (
            record is None
            or record.tenant_id != tenant_id
            or record.session_id != session_id
            or record.evidence_type != evidence_type
            or evidence_result_id in self.not_effective
        ):
            return False
        self.not_effective.add(evidence_result_id)
        return True


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
    evidence_repo = FakeEvidenceRepository()
    svc = EvidenceResultService(repo, AuditService(audit_repo), evidence_repo)
    return svc, repo, audit_repo


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
async def test_repeated_idempotency_key_resolves_to_the_same_result_not_a_new_one(
    service,
) -> None:
    """Invariant-12 remediation: a retried submission must not silently
    create a duplicate evidence result."""
    svc, repo, _ = service
    session_id = uuid4()

    first = await svc.create(
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
        result={"similarity": 0.91},
        score=0.91,
        idempotency_key="req-abc",
    )
    second = await svc.create(
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
        result={"similarity": 0.91},
        score=0.91,
        idempotency_key="req-abc",
    )

    assert first.id == second.id
    assert repo.add_calls == 1


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
async def test_supersede_rejects_a_result_belonging_to_a_different_session(service) -> None:
    """WF-HV-009 Finding A: session B must not be able to supersede (and
    thereby silently deactivate) session A's effective evidence result
    merely by supplying its ID. Confirmed live against real Postgres
    before this fix -- session A's result vanished from its own
    effective-evidence set with no error and no relationship between the
    two sessions."""
    svc, repo, _audit_repo = service
    session_a = uuid4()
    session_b = uuid4()

    victim = await svc.create(
        tenant_id="tenant-a",
        session_id=session_a,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
    )

    with pytest.raises(InvalidSupersessionError):
        await svc.supersede(
            evidence_result_id=victim.id,
            tenant_id="tenant-a",
            session_id=session_b,
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="attacker-producer",
            producer_version="1.0.0",
        )

    # the victim's result is untouched -- still effective, still session A's
    assert victim.id not in repo.not_effective
    assert repo.add_calls == 1  # only the original create(), no attacker row
    effective_a = await svc.list_effective_for_session(session_id=session_a, tenant_id="tenant-a")
    assert [r.id for r in effective_a] == [victim.id]


@pytest.mark.asyncio
async def test_supersede_rejects_a_result_of_a_different_evidence_type(service) -> None:
    """Same defect, addressed via a mismatched evidence_type rather than a
    mismatched session -- the caller's own claimed evidence_type must
    match the target row's actual evidence_type, not merely be trusted."""
    svc, repo, _audit_repo = service
    session_id = uuid4()

    original = await svc.create(
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
    )

    with pytest.raises(InvalidSupersessionError):
        await svc.supersede(
            evidence_result_id=original.id,
            tenant_id="tenant-a",
            session_id=session_id,
            evidence_type=EvidenceResultType.FACE_QUALITY,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0.1",
        )

    assert original.id not in repo.not_effective
    assert repo.add_calls == 1


@pytest.mark.asyncio
async def test_supersede_rejects_a_result_already_superseded(service) -> None:
    """Prevents a non-linear/ambiguous lineage: once a result has been
    superseded, it is no longer a valid supersession target -- a second
    attempt to supersede the same original (e.g. a confused or replayed
    caller) must not silently succeed a second time."""
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
    await svc.supersede(
        evidence_result_id=original.id,
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.1",
    )

    with pytest.raises(InvalidSupersessionError):
        await svc.supersede(
            evidence_result_id=original.id,
            tenant_id="tenant-a",
            session_id=session_id,
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0.2",
        )

    assert repo.add_calls == 2  # original + first (valid) supersession only


@pytest.mark.asyncio
async def test_supersede_rejects_a_nonexistent_evidence_result_id(service) -> None:
    svc, repo, _audit_repo = service

    with pytest.raises(InvalidSupersessionError):
        await svc.supersede(
            evidence_result_id=uuid4(),
            tenant_id="tenant-a",
            session_id=uuid4(),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0.0",
        )

    assert repo.add_calls == 0


@pytest.mark.asyncio
async def test_create_rejects_a_source_reference_from_a_different_session(service) -> None:
    """WF-HV-009 Finding B: source_reference's DB foreign key only proves
    the Evidence row exists somewhere -- not that it belongs to this
    session. Confirmed live before this check existed: a caller could
    create a result that falsely claims derivation from another
    session's (or tenant's) raw evidence capture, with no error."""
    svc, repo, _audit_repo = service
    own_session = uuid4()
    other_session = uuid4()
    foreign_evidence_id = uuid4()
    svc.evidence_repository.records[foreign_evidence_id] = Evidence(
        id=foreign_evidence_id,
        session_id=other_session,
        tenant_id="tenant-a",
        evidence_type=EvidenceType.SELFIE,
        source=EvidenceSource.CLIENT,
        object_key="tenant-a/other/selfie.jpg",
        checksum="deadbeef",
        mime_type="image/jpeg",
        size_bytes=100,
    )

    with pytest.raises(InvalidProvenanceReferenceError):
        await svc.create(
            tenant_id="tenant-a",
            session_id=own_session,
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0.0",
            source_reference=foreign_evidence_id,
        )

    assert repo.add_calls == 0


@pytest.mark.asyncio
async def test_create_rejects_a_parent_evidence_result_from_a_different_session(service) -> None:
    """Same defect, on the result-to-result lineage field instead of the
    capture-to-result one -- parent_evidence_result_ids has no FK
    enforcement at all, so this is the only check standing between a
    caller and a fabricated cross-session/cross-tenant lineage claim."""
    svc, repo, _audit_repo = service
    own_session = uuid4()
    other_session = uuid4()

    foreign_result = await svc.create(
        tenant_id="tenant-a",
        session_id=other_session,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
    )
    assert repo.add_calls == 1

    with pytest.raises(InvalidProvenanceReferenceError):
        await svc.create(
            tenant_id="tenant-a",
            session_id=own_session,
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0.0",
            parent_evidence_result_ids=(foreign_result.id,),
        )

    assert repo.add_calls == 1  # only the legitimate foreign_result, no forged row


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
async def test_integrity_reference_changes_with_score(service) -> None:
    """WF-HV-009 integrity/checksum: score is one of the three "universal"
    EvidenceResult attributes core.decision.condition_eval evaluates
    directly (alongside status/quality) -- a threshold-based policy
    condition can fire differently purely because of score. Before this
    fix, two results differing ONLY in score collided on an identical
    integrity_reference, silently failing to correspond to actual
    decision-relevant persisted content (EVD-3.9.2)."""
    svc, _repo, _audit_repo = service
    session_id = uuid4()

    lower = await svc.create(
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
        score=0.5,
    )
    higher = await svc.create(
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
        score=0.95,
    )

    assert lower.integrity_reference != higher.integrity_reference


@pytest.mark.asyncio
async def test_integrity_reference_changes_with_quality(service) -> None:
    """Same property, on quality instead of score -- the other field
    condition_eval treats as universal."""
    svc, _repo, _audit_repo = service
    session_id = uuid4()

    lower = await svc.create(
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_QUALITY,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
        quality=0.3,
    )
    higher = await svc.create(
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_QUALITY,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
        quality=0.9,
    )

    assert lower.integrity_reference != higher.integrity_reference


@pytest.mark.asyncio
async def test_integrity_reference_stable_when_score_and_quality_match(service) -> None:
    """The other half of the same property: matching score/quality (not
    merely omitting both) still converges on an identical
    integrity_reference -- this is a completeness fix, not a change to
    the "same logical content -> same reference" determinism guarantee
    test_integrity_reference_is_server_computed_and_deterministic already
    covers for the score=None/quality=None default case."""
    svc, _repo, _audit_repo = service
    session_id = uuid4()

    first = await svc.create(
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
        score=0.77,
        quality=0.88,
    )
    second = await svc.create(
        tenant_id="tenant-a",
        session_id=session_id,
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
        score=0.77,
        quality=0.88,
    )

    assert first.integrity_reference == second.integrity_reference


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
