"""WF-006 Finding B / WF-4.6.4 / WF-4.17.4: the EXPIRED transition's
required audit event is recorded exactly once, by
VerificationSessionService.get() itself at the point its own CAS write
succeeds -- never by a specific caller's own ad hoc check. Every caller
that can trigger a lazy expiry (a direct GET, /submit, evidence upload,
/cancel -- all of which route a session through get()) is covered
uniformly. Real-Postgres proof of the same property lives in
tests/integration/test_verification_session_expiry_audit.py; these tests
exercise the service's own audit-recording logic against fakes.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from core.audit.enums import AuditActorType, AuditEventType, AuditStatus
from core.audit.models import AuditEvent
from core.audit.service import AuditService
from core.verification.enums import AssuranceLevel, VerificationStatus
from core.verification.exceptions import ConcurrentTransitionError, SessionAlreadyTerminalError
from core.verification.models import VerificationSession
from core.verification.service import VerificationSessionService

TENANT = "tenant-a"


class FakeSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, VerificationSession] = {}
        self.update_calls = 0

    async def add(self, session: VerificationSession, idempotency_key: str | None = None):
        self.sessions[session.id] = session
        return session.model_copy()

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
        self.update_calls += 1
        current = self.sessions.get(session.id)
        if current is None or current.status != expected_status:
            raise ConcurrentTransitionError(
                f"session_id={session.id!s} was not in status {expected_status.value!r}"
            )
        self.sessions[session.id] = session
        return session


class FakeAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def add(self, event: AuditEvent, dedupe_key: str | None = None) -> AuditEvent:
        self.events.append(event)
        return event

    async def get_by_dedupe_key(self, tenant_id, session_id, dedupe_key):
        return None

    async def list_for_session(self, session_id, tenant_id):
        return [e for e in self.events if e.session_id == session_id]


def _expired_session(status: VerificationStatus) -> VerificationSession:
    now = datetime.now(UTC)
    return VerificationSession(
        tenant_id=TENANT,
        status=status,
        assurance_level=AssuranceLevel.STANDARD,
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(minutes=1),
    )


@pytest.fixture
def repo() -> FakeSessionRepository:
    return FakeSessionRepository()


@pytest.fixture
def audit_repo() -> FakeAuditRepository:
    return FakeAuditRepository()


@pytest.fixture
def audit_service(audit_repo: FakeAuditRepository) -> AuditService:
    return AuditService(audit_repo)


@pytest.fixture
def service(
    repo: FakeSessionRepository, audit_service: AuditService
) -> VerificationSessionService:
    return VerificationSessionService(repo, audit_service, session_ttl_minutes=30)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [VerificationStatus.CREATED, VerificationStatus.CAPTURING, VerificationStatus.SUBMITTED],
)
async def test_get_records_session_expired_for_every_pre_processing_status(
    service, repo, audit_repo, status
) -> None:
    session = _expired_session(status)
    await repo.add(session)

    fetched = await service.get(session_id=session.id, tenant_id=TENANT)

    assert fetched.status is VerificationStatus.EXPIRED
    events = [e for e in audit_repo.events if e.event_type == AuditEventType.SESSION_EXPIRED]
    assert len(events) == 1
    event = events[0]
    assert event.session_id == session.id
    assert event.tenant_id == TENANT
    assert event.actor_type is AuditActorType.SYSTEM
    assert event.status is AuditStatus.SUCCESS
    assert event.metadata == {"from_status": status.value, "to_status": "EXPIRED"}


@pytest.mark.asyncio
async def test_get_records_no_audit_when_the_session_is_not_past_expiry(
    service, repo, audit_repo
) -> None:
    now = datetime.now(UTC)
    session = VerificationSession(
        tenant_id=TENANT,
        status=VerificationStatus.CREATED,
        assurance_level=AssuranceLevel.STANDARD,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    await repo.add(session)

    await service.get(session_id=session.id, tenant_id=TENANT)

    assert audit_repo.events == []


@pytest.mark.asyncio
async def test_repeated_get_on_an_already_expired_session_never_re_audits(
    service, repo, audit_repo
) -> None:
    """expire_if_needed() only returns True the one time it performs the
    transition -- a session already sitting in EXPIRED must never
    produce a second SESSION_EXPIRED event on a later GET."""
    session = _expired_session(VerificationStatus.CREATED)
    await repo.add(session)

    await service.get(session_id=session.id, tenant_id=TENANT)
    await service.get(session_id=session.id, tenant_id=TENANT)
    await service.get(session_id=session.id, tenant_id=TENANT)

    events = [e for e in audit_repo.events if e.event_type == AuditEventType.SESSION_EXPIRED]
    assert len(events) == 1


@pytest.mark.asyncio
async def test_cancel_on_an_expired_session_still_audits_the_expiry_before_rejecting(
    service, repo, audit_repo
) -> None:
    """cancel() calls get() internally first. Even though cancel() itself
    then rejects with SessionAlreadyTerminalError (the session is now
    EXPIRED, a terminal state), the expiry transition it observed along
    the way is a real, legitimate side effect that must still be
    audited -- proving the fix reaches cancel()'s call path too, not just
    a direct GET."""
    session = _expired_session(VerificationStatus.CREATED)
    await repo.add(session)

    with pytest.raises(SessionAlreadyTerminalError):
        await service.cancel(session_id=session.id, tenant_id=TENANT)

    events = [e for e in audit_repo.events if e.event_type == AuditEventType.SESSION_EXPIRED]
    assert len(events) == 1


@pytest.mark.asyncio
async def test_audit_service_is_a_required_constructor_argument() -> None:
    """WF-006 Finding B: audit_service is required, not optional --
    guards against the exact gap this finding closed reopening silently
    at a future call site."""
    with pytest.raises(TypeError):
        VerificationSessionService(FakeSessionRepository())  # type: ignore[call-arg]
