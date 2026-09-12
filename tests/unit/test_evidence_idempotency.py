"""WF-001 §10 / WF-4.9.2-4.9.4: evidence-submission idempotency's canonical
fingerprint -- equivalent replay converges on the original evidence row;
materially different reuse of the same Idempotency-Key (a different
evidence_type, or different file content entirely) is rejected with
IdempotencyKeyReusedError, never silently resolved to the first write.
Real-Postgres + MinIO proof of the concurrent-insert race lives in
tests/integration/test_evidence_idempotency.py; these tests exercise the
service's own comparison logic against fakes, including the
concurrent-insert recovery path via a forced conflict hook.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from core.audit.service import AuditService
from core.evidence.enums import EvidenceSource, EvidenceType
from core.evidence.exceptions import IdempotencyKeyConflictError, IdempotencyKeyReusedError
from core.evidence.models import Evidence
from core.evidence.service import EvidenceService
from core.verification.enums import AssuranceLevel, VerificationStatus
from core.verification.exceptions import ConcurrentTransitionError
from core.verification.models import VerificationSession
from core.verification.service import VerificationSessionService

TENANT = "tenant-a"

MINIMAL_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"


class FakeVerificationSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, VerificationSession] = {}

    async def add(self, session: VerificationSession, idempotency_key: str | None = None):
        self.sessions[session.id] = session
        return session

    async def get(self, session_id: UUID, tenant_id: str) -> VerificationSession | None:
        session = self.sessions.get(session_id)
        if session is None or session.tenant_id != tenant_id:
            return None
        return session.model_copy()

    async def get_by_idempotency_key(self, tenant_id: str, idempotency_key: str):
        return None

    async def list(self, tenant_id: str):
        return [s for s in self.sessions.values() if s.tenant_id == tenant_id]

    async def update(
        self, session: VerificationSession, *, expected_status: VerificationStatus
    ) -> VerificationSession:
        current = self.sessions.get(session.id)
        if current is None or current.status != expected_status:
            raise ConcurrentTransitionError(
                f"session_id={session.id!s} was not in status {expected_status.value!r}"
            )
        # A copy, deliberately -- see test_verification_session_service.py's
        # identical fake for why storing the caller's own live object
        # here would let a later transition_to() call corrupt what this
        # dict believes is "currently stored."
        self.sessions[session.id] = session.model_copy()
        return session


class FakeEvidenceRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, Evidence] = {}
        self.idempotency_keys: dict[tuple[str, UUID, str], UUID] = {}
        self.add_calls = 0
        # When set, the NEXT add() call raises IdempotencyKeyConflictError
        # instead of applying its own write, and ATOMICALLY makes this
        # winner row visible via get_by_idempotency_key() at that exact
        # moment -- not before. This models the real timing of the race:
        # this attempt's own upfront get_by_idempotency_key() check (which
        # runs strictly before add()) must still see nothing, matching a
        # concurrent request that commits its equivalent row strictly
        # between that check and this attempt's own INSERT.
        self._pending_conflict_winner: Evidence | None = None
        # Set directly (not via stage_concurrent_winner) to simulate the
        # "should be unreachable" case: add() conflicts, but no winner is
        # ever visible afterward.
        self.force_next_add_conflict_with_no_winner = False

    async def add(self, evidence: Evidence, idempotency_key: str | None = None) -> Evidence:
        self.add_calls += 1
        if self._pending_conflict_winner is not None:
            winner = self._pending_conflict_winner
            self._pending_conflict_winner = None
            self.records[winner.id] = winner
            if idempotency_key is not None:
                self.idempotency_keys[
                    (winner.tenant_id, winner.session_id, idempotency_key)
                ] = winner.id
            raise IdempotencyKeyConflictError("simulated concurrent insert")
        if self.force_next_add_conflict_with_no_winner:
            self.force_next_add_conflict_with_no_winner = False
            raise IdempotencyKeyConflictError("simulated concurrent insert, no winner ever visible")
        self.records[evidence.id] = evidence
        if idempotency_key is not None:
            self.idempotency_keys[(evidence.tenant_id, evidence.session_id, idempotency_key)] = (
                evidence.id
            )
        return evidence

    async def get_by_idempotency_key(self, tenant_id, session_id, idempotency_key):
        evidence_id = self.idempotency_keys.get((tenant_id, session_id, idempotency_key))
        return self.records.get(evidence_id) if evidence_id is not None else None

    async def get(self, evidence_id, tenant_id):
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

    async def has_dependent_evidence_results(self, evidence_id, tenant_id):
        return False

    async def delete_content(self, evidence_id, tenant_id):
        return bool(self.records.pop(evidence_id, None))

    async def add_tombstone(self, tombstone):
        raise NotImplementedError

    async def get_tombstone(self, evidence_id, tenant_id):
        return None

    async def mark_tombstone_executed(self, evidence_id, tenant_id, executed_at):
        raise NotImplementedError

    def stage_concurrent_winner(
        self, *, tenant_id: str, session_id: UUID, fingerprint: str
    ) -> Evidence:
        """The NEXT add() call will fail with IdempotencyKeyConflictError
        and, at that exact moment, make this winner row visible via
        get_by_idempotency_key() -- deliberately NOT visible before then,
        so a test using this still exercises a genuine upfront-check-sees-
        nothing-but-insert-conflicts race, not the upfront-match path."""
        evidence = Evidence(
            session_id=session_id,
            tenant_id=tenant_id,
            evidence_type=EvidenceType.SELFIE,
            source=EvidenceSource.CLIENT,
            object_key=f"{tenant_id}/{session_id}/selfie/winner",
            checksum="winner-checksum",
            mime_type="image/jpeg",
            size_bytes=1,
            fingerprint=fingerprint,
        )
        self._pending_conflict_winner = evidence
        return evidence


class FakeObjectStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.put_calls = 0
        self.delete_calls = 0

    async def put(self, object_key: str, content: bytes, content_type: str) -> None:
        self.put_calls += 1
        self.blobs[object_key] = content

    async def get(self, object_key: str) -> bytes:
        return self.blobs[object_key]

    async def delete(self, object_key: str) -> None:
        self.delete_calls += 1
        self.blobs.pop(object_key, None)


class FakeAuditRepository:
    def __init__(self) -> None:
        self.events: list = []

    async def add(self, event, dedupe_key=None):
        self.events.append(event)
        return event

    async def get_by_dedupe_key(self, tenant_id, session_id, dedupe_key):
        return None

    async def list_for_session(self, session_id, tenant_id):
        return []


def _active_session() -> VerificationSession:
    now = datetime.now(UTC)
    return VerificationSession(
        tenant_id=TENANT,
        status=VerificationStatus.CREATED,
        assurance_level=AssuranceLevel.STANDARD,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )


@pytest.fixture
def session_repo() -> FakeVerificationSessionRepository:
    return FakeVerificationSessionRepository()


@pytest.fixture
def evidence_repo() -> FakeEvidenceRepository:
    return FakeEvidenceRepository()


@pytest.fixture
def storage() -> FakeObjectStorage:
    return FakeObjectStorage()


@pytest.fixture
async def service(session_repo, evidence_repo, storage) -> EvidenceService:
    return EvidenceService(
        evidence_repo,
        VerificationSessionService(
            session_repo,
            audit_service=AuditService(FakeAuditRepository()),
            session_ttl_minutes=30,
        ),
        storage,
        AuditService(FakeAuditRepository()),
    )


@pytest.fixture
async def active_session(session_repo) -> VerificationSession:
    session = _active_session()
    await session_repo.add(session)
    return session


@pytest.mark.asyncio
async def test_replay_with_matching_fields_converges_on_the_original_evidence(
    service, evidence_repo, storage, active_session
) -> None:
    first = await service.add(
        session_id=active_session.id,
        tenant_id=TENANT,
        evidence_type=EvidenceType.SELFIE,
        content=MINIMAL_JPEG_BYTES,
        checksum="checksum-abc",
        metadata={},
        idempotency_key="req-1",
    )

    replayed = await service.add(
        session_id=active_session.id,
        tenant_id=TENANT,
        evidence_type=EvidenceType.SELFIE,
        content=MINIMAL_JPEG_BYTES,
        checksum="checksum-abc",
        metadata={},
        idempotency_key="req-1",
    )

    assert replayed.id == first.id
    assert evidence_repo.add_calls == 1
    assert storage.put_calls == 1


@pytest.mark.asyncio
async def test_replay_with_different_content_is_rejected(
    service, evidence_repo, storage, active_session
) -> None:
    await service.add(
        session_id=active_session.id,
        tenant_id=TENANT,
        evidence_type=EvidenceType.SELFIE,
        content=MINIMAL_JPEG_BYTES,
        checksum="checksum-abc",
        metadata={},
        idempotency_key="req-1",
    )

    with pytest.raises(IdempotencyKeyReusedError):
        await service.add(
            session_id=active_session.id,
            tenant_id=TENANT,
            evidence_type=EvidenceType.SELFIE,
            content=MINIMAL_JPEG_BYTES,
            checksum="checksum-DIFFERENT",  # materially different content
            metadata={},
            idempotency_key="req-1",
        )

    # rejected before ANY new mutation
    assert evidence_repo.add_calls == 1
    assert storage.put_calls == 1


@pytest.mark.asyncio
async def test_replay_with_a_different_evidence_type_is_rejected(
    service, active_session
) -> None:
    await service.add(
        session_id=active_session.id,
        tenant_id=TENANT,
        evidence_type=EvidenceType.SELFIE,
        content=MINIMAL_JPEG_BYTES,
        checksum="checksum-abc",
        metadata={},
        idempotency_key="req-1",
    )

    with pytest.raises(IdempotencyKeyReusedError):
        await service.add(
            session_id=active_session.id,
            tenant_id=TENANT,
            evidence_type=EvidenceType.DOCUMENT,  # materially different
            content=MINIMAL_JPEG_BYTES,
            checksum="checksum-abc",
            metadata={},
            idempotency_key="req-1",
        )


@pytest.mark.asyncio
async def test_no_idempotency_key_always_creates_fresh_evidence(service, active_session) -> None:
    first = await service.add(
        session_id=active_session.id,
        tenant_id=TENANT,
        evidence_type=EvidenceType.SELFIE,
        content=MINIMAL_JPEG_BYTES,
        checksum="checksum-abc",
        metadata={},
    )
    second = await service.add(
        session_id=active_session.id,
        tenant_id=TENANT,
        evidence_type=EvidenceType.SELFIE,
        content=MINIMAL_JPEG_BYTES,
        checksum="checksum-abc",
        metadata={},
    )

    assert first.id != second.id


@pytest.mark.asyncio
async def test_the_same_idempotency_key_is_scoped_per_session(
    service, session_repo, active_session
) -> None:
    """WF-001 §10: the evidence fingerprint and the table's UNIQUE
    constraint both include session_id -- the identical raw key reused
    across two different sessions of the same tenant must never collide."""
    other_session = _active_session()
    await session_repo.add(other_session)

    first = await service.add(
        session_id=active_session.id,
        tenant_id=TENANT,
        evidence_type=EvidenceType.SELFIE,
        content=MINIMAL_JPEG_BYTES,
        checksum="checksum-abc",
        metadata={},
        idempotency_key="shared-raw-key",
    )
    second = await service.add(
        session_id=other_session.id,
        tenant_id=TENANT,
        evidence_type=EvidenceType.SELFIE,
        content=MINIMAL_JPEG_BYTES,
        checksum="checksum-abc",
        metadata={},
        idempotency_key="shared-raw-key",
    )

    assert first.id != second.id
    assert first.session_id == active_session.id
    assert second.session_id == other_session.id


@pytest.mark.asyncio
async def test_concurrent_insert_conflict_recovers_by_converging_on_a_matching_winner(
    service, evidence_repo, storage, active_session
) -> None:
    from core.evidence.service import _compute_evidence_submission_fingerprint

    fingerprint = _compute_evidence_submission_fingerprint(
        tenant_id=TENANT,
        session_id=active_session.id,
        evidence_type=EvidenceType.SELFIE,
        checksum="checksum-abc",
    )
    winner = evidence_repo.stage_concurrent_winner(
        tenant_id=TENANT, session_id=active_session.id, fingerprint=fingerprint
    )

    result = await service.add(
        session_id=active_session.id,
        tenant_id=TENANT,
        evidence_type=EvidenceType.SELFIE,
        content=MINIMAL_JPEG_BYTES,
        checksum="checksum-abc",
        metadata={},
        idempotency_key="req-race",
    )

    assert result.id == winner.id
    # the recovery path was genuinely exercised, not the upfront-match path
    assert evidence_repo.add_calls == 1
    # the losing attempt's own object write was cleaned up
    assert storage.delete_calls == 1


@pytest.mark.asyncio
async def test_concurrent_insert_conflict_with_a_mismatched_winner_is_rejected(
    service, evidence_repo, storage, active_session
) -> None:
    from core.evidence.service import _compute_evidence_submission_fingerprint

    mismatched_fingerprint = _compute_evidence_submission_fingerprint(
        tenant_id=TENANT,
        session_id=active_session.id,
        evidence_type=EvidenceType.SELFIE,
        checksum="checksum-DIFFERENT",
    )
    evidence_repo.stage_concurrent_winner(
        tenant_id=TENANT, session_id=active_session.id, fingerprint=mismatched_fingerprint
    )

    with pytest.raises(IdempotencyKeyReusedError):
        await service.add(
            session_id=active_session.id,
            tenant_id=TENANT,
            evidence_type=EvidenceType.SELFIE,
            content=MINIMAL_JPEG_BYTES,
            checksum="checksum-abc",
            metadata={},
            idempotency_key="req-race",
        )

    assert storage.delete_calls == 1


@pytest.mark.asyncio
async def test_concurrent_insert_conflict_with_no_recoverable_row_reraises(
    service, evidence_repo, active_session
) -> None:
    evidence_repo.force_next_add_conflict_with_no_winner = True

    with pytest.raises(IdempotencyKeyConflictError, match="no winner ever visible"):
        await service.add(
            session_id=active_session.id,
            tenant_id=TENANT,
            evidence_type=EvidenceType.SELFIE,
            content=MINIMAL_JPEG_BYTES,
            checksum="checksum-abc",
            metadata={},
            idempotency_key="req-race-orphan",
        )
