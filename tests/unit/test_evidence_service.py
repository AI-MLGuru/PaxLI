"""DE-004 Phase 4 mandatory acceptance gate: WF-4.19.2 / DE-003 §13 --
evidence submission MUST be rejected for every one of the six terminal
session states, not just EXPIRED/CANCELLED (DE-002 landmine 2). Real-
Postgres + MinIO proof of the same property lives in
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
from core.verification.enums import TERMINAL_STATUSES, AssuranceLevel, VerificationStatus
from core.verification.models import VerificationSession
from core.verification.service import SessionExpiredError, VerificationSessionService

TENANT = "tenant-a"

# A minimal, structurally valid JPEG (real signature bytes), same fixture
# tests/conftest.py uses for server-side media validation (SEC-7.22.2).
MINIMAL_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"

NON_TERMINAL_STATUSES = tuple(
    status for status in VerificationStatus if status not in TERMINAL_STATUSES
)


class FakeVerificationSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, VerificationSession] = {}

    async def add(self, session: VerificationSession, idempotency_key: str | None = None):
        self.sessions[session.id] = session
        return session

    async def get(self, session_id: UUID, tenant_id: str) -> VerificationSession | None:
        session = self.sessions.get(session_id)
        return session if session and session.tenant_id == tenant_id else None

    async def get_by_idempotency_key(self, tenant_id: str, idempotency_key: str):
        return None

    async def list(self, tenant_id: str):
        return [s for s in self.sessions.values() if s.tenant_id == tenant_id]

    async def update(self, session: VerificationSession) -> VerificationSession:
        self.sessions[session.id] = session
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
    terminal state to prove the evidence-submission guard, not exercise the
    session state machine itself. `expires_at` is set in the future so
    VerificationSessionService.get()'s expire_if_needed() side effect never
    interferes (and for CREATED/PROCESSING it would be a no-op on a
    non-terminal status anyway)."""
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
@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES, key=lambda s: s.value))
async def test_evidence_submission_is_rejected_for_every_terminal_status(service, status) -> None:
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
@pytest.mark.parametrize("status", NON_TERMINAL_STATUSES)
async def test_evidence_submission_is_accepted_for_every_non_terminal_status(
    service, status
) -> None:
    """The mirror image, so the fix is proven to widen the guard correctly
    rather than simply rejecting everything: CREATED and PROCESSING must
    remain unaffected."""
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


def test_terminal_and_non_terminal_status_sets_are_exhaustive_and_disjoint() -> None:
    """Guards against a future new VerificationStatus member silently
    falling into neither set."""
    all_statuses = set(VerificationStatus)
    assert TERMINAL_STATUSES | set(NON_TERMINAL_STATUSES) == all_statuses
    assert TERMINAL_STATUSES.isdisjoint(NON_TERMINAL_STATUSES)
    assert TERMINAL_STATUSES == {
        VerificationStatus.VERIFIED,
        VerificationStatus.REJECTED,
        VerificationStatus.REVIEW_REQUIRED,
        VerificationStatus.INCONCLUSIVE,
        VerificationStatus.EXPIRED,
        VerificationStatus.CANCELLED,
    }
