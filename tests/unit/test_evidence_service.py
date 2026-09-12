"""WF-001 §8 / WF-4.19.2: evidence submission MUST be rejected outside the
allow-list {CREATED, CAPTURING} -- not merely outside the terminal states.
SUBMITTED and PROCESSING must also reject ordinary submission despite
neither being terminal, because the client has already signaled "done" by
calling /submit. Real-Postgres + MinIO proof of the same property lives in
tests/integration/test_evidence_service_terminal_state.py; these tests
exercise the guard itself, and that rejection precedes any mutation, purely
in memory.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from core.audit.models import AuditEvent
from core.audit.service import AuditService
from core.evidence.enums import EvidenceSource, EvidenceType
from core.evidence.models import Evidence
from core.evidence.service import EvidenceService
from core.verification.enums import (
    EVIDENCE_SUBMISSION_ALLOWED_STATUSES,
    AssuranceLevel,
    VerificationStatus,
)
from core.verification.exceptions import ConcurrentTransitionError
from core.verification.models import VerificationSession
from core.verification.service import SessionExpiredError, VerificationSessionService

TENANT = "tenant-a"

# A minimal, structurally valid JPEG (real signature bytes), same fixture
# tests/conftest.py uses for server-side media validation (SEC-7.22.2).
MINIMAL_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"

EVIDENCE_SUBMISSION_REJECTED_STATUSES = tuple(
    status for status in VerificationStatus if status not in EVIDENCE_SUBMISSION_ALLOWED_STATUSES
)


class FakeVerificationSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, VerificationSession] = {}

    async def add(self, session: VerificationSession, idempotency_key: str | None = None):
        self.sessions[session.id] = session
        return session

    async def get(self, session_id: UUID, tenant_id: str) -> VerificationSession | None:
        # A fresh copy, deliberately -- see test_verification_session_service.py's
        # identical fake for why a real DB-backed repository never hands
        # back a live, caller-mutable reference here.
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
        self.add_calls = 0

    async def add(self, evidence: Evidence, idempotency_key: str | None = None) -> Evidence:
        self.add_calls += 1
        self.records[evidence.id] = evidence
        return evidence

    async def get_by_idempotency_key(self, tenant_id, session_id, idempotency_key):
        return None

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


class FakeObjectStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.put_calls = 0

    async def put(self, object_key: str, content: bytes, content_type: str) -> None:
        self.put_calls += 1
        self.blobs[object_key] = content

    async def get(self, object_key: str) -> bytes:
        return self.blobs[object_key]

    async def delete(self, object_key: str) -> None:
        self.blobs.pop(object_key, None)


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


def _session_in_status(status: VerificationStatus) -> VerificationSession:
    """Constructed directly in the target status, bypassing
    transition_to()'s legality checks -- these tests seed an arbitrary
    status to prove the evidence-submission guard, not exercise the
    session state machine itself. `expires_at` is set in the future so
    VerificationSessionService.get()'s expire_if_needed() side effect
    never interferes."""
    now = datetime.now(UTC)
    return VerificationSession(
        tenant_id=TENANT,
        status=status,
        assurance_level=AssuranceLevel.STANDARD,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )


@pytest.fixture
def service():
    session_repo = FakeVerificationSessionRepository()
    evidence_repo = FakeEvidenceRepository()
    storage = FakeObjectStorage()
    audit_repo = FakeAuditRepository()
    svc = EvidenceService(
        evidence_repo,
        VerificationSessionService(session_repo, session_ttl_minutes=30),
        storage,
        AuditService(audit_repo),
    )
    return svc, session_repo, evidence_repo, storage, audit_repo


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", sorted(EVIDENCE_SUBMISSION_REJECTED_STATUSES, key=lambda s: s.value)
)
async def test_evidence_submission_is_rejected_outside_the_allow_list(service, status) -> None:
    svc, session_repo, evidence_repo, storage, _audit_repo = service
    session = _session_in_status(status)
    await session_repo.add(session)

    with pytest.raises(SessionExpiredError):
        await svc.add(
            session_id=session.id,
            tenant_id=TENANT,
            evidence_type=EvidenceType.SELFIE,
            content=MINIMAL_JPEG_BYTES,
            checksum="deadbeef",
            metadata={},
        )

    # rejected before ANY mutation -- no object write, no EvidenceRecord
    assert storage.put_calls == 0
    assert evidence_repo.add_calls == 0
    assert evidence_repo.records == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", sorted(EVIDENCE_SUBMISSION_ALLOWED_STATUSES, key=lambda s: s.value)
)
async def test_evidence_submission_is_accepted_for_every_allowed_status(service, status) -> None:
    """The mirror image, so the fix is proven to scope the guard correctly
    rather than simply rejecting everything: CREATED and CAPTURING must
    remain accepted."""
    svc, session_repo, evidence_repo, storage, _audit_repo = service
    session = _session_in_status(status)
    await session_repo.add(session)

    evidence = await svc.add(
        session_id=session.id,
        tenant_id=TENANT,
        evidence_type=EvidenceType.SELFIE,
        content=MINIMAL_JPEG_BYTES,
        checksum="deadbeef",
        metadata={},
    )

    assert evidence.source == EvidenceSource.CLIENT
    assert storage.put_calls == 1
    assert evidence_repo.add_calls == 1


def test_allowed_and_rejected_status_sets_are_exhaustive_and_disjoint() -> None:
    """Guards against a future new VerificationStatus member silently
    falling into neither set."""
    all_statuses = set(VerificationStatus)
    assert EVIDENCE_SUBMISSION_ALLOWED_STATUSES | set(EVIDENCE_SUBMISSION_REJECTED_STATUSES) == (
        all_statuses
    )
    assert EVIDENCE_SUBMISSION_ALLOWED_STATUSES.isdisjoint(EVIDENCE_SUBMISSION_REJECTED_STATUSES)
    assert EVIDENCE_SUBMISSION_ALLOWED_STATUSES == {
        VerificationStatus.CREATED,
        VerificationStatus.CAPTURING,
    }
    assert set(EVIDENCE_SUBMISSION_REJECTED_STATUSES) == {
        VerificationStatus.SUBMITTED,
        VerificationStatus.PROCESSING,
        VerificationStatus.COMPLETED,
        VerificationStatus.EXPIRED,
        VerificationStatus.CANCELLED,
    }
