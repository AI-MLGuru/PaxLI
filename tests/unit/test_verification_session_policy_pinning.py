"""DE-002/DE-003 §1 early policy binding: VerificationSessionService.create()
resolves the tenant's ACTIVE policy exactly once and pins it onto the new
session, never re-resolved. Real-Postgres proof (including the "policy
v3->v4 mid-session: v3 always" adversarial case against genuine concurrent
activation) lives in tests/integration/test_session_policy_pinning.py;
these tests exercise the service's own logic against fakes.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from core.policy.enums import PolicyStatus
from core.policy.exceptions import NoActivePolicyError
from core.policy.models import VerificationPolicy
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel
from core.verification.exceptions import ConcurrentTransitionError
from core.verification.models import VerificationSession
from core.verification.service import VerificationSessionService

TENANT = "tenant-a"


class FakePolicyRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, VerificationPolicy] = {}

    async def add(self, policy: VerificationPolicy, idempotency_key: str | None = None):
        self.records[policy.id] = policy
        return policy

    async def get_by_idempotency_key(self, tenant_id, idempotency_key):
        return None

    async def mark_superseded(self, policy_row_id, tenant_id, superseded_at):
        record = self.records[policy_row_id]
        self.records[policy_row_id] = record.model_copy(
            update={"status": PolicyStatus.SUPERSEDED, "superseded_at": superseded_at}
        )

    async def get(self, policy_row_id, tenant_id):
        record = self.records.get(policy_row_id)
        return record if record and record.tenant_id == tenant_id else None

    async def get_active(self, tenant_id: str, assurance_level: AssuranceLevel):
        for record in self.records.values():
            if (
                record.tenant_id == tenant_id
                and record.assurance_level == assurance_level
                and record.status == PolicyStatus.ACTIVE
            ):
                return record
        return None

    async def get_version(self, policy_id, version, tenant_id):
        for record in self.records.values():
            if (
                record.policy_id == policy_id
                and record.version == version
                and record.tenant_id == tenant_id
            ):
                return record
        return None

    async def get_max_version(self, policy_id, tenant_id):
        versions = [
            r.version
            for r in self.records.values()
            if r.policy_id == policy_id and r.tenant_id == tenant_id
        ]
        return max(versions, default=0)

    async def list_versions(self, policy_id, tenant_id):
        return [
            r
            for r in self.records.values()
            if r.policy_id == policy_id and r.tenant_id == tenant_id
        ]


class FakeAuditRepository:
    def __init__(self) -> None:
        self.events = []

    async def add(self, event, dedupe_key=None):
        self.events.append(event)
        return event

    async def get_by_dedupe_key(self, tenant_id, session_id, dedupe_key):
        return None

    async def list_for_session(self, session_id, tenant_id):
        return []


class NullSchemaCatalog:
    """No policy content is ever validated in these tests (get_active() is
    a pure read of an already-stored policy), so this catalog is never
    actually consulted -- present only because PolicyService requires one."""

    def is_known_evidence_type(self, evidence_type: str) -> bool:
        return True

    def supports_field(self, evidence_type: str, field: str) -> bool:
        return True


class FakeSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, VerificationSession] = {}
        self.idempotency_keys: dict[tuple[str, str], UUID] = {}
        self.add_calls = 0

    async def add(self, session: VerificationSession, idempotency_key: str | None = None):
        self.add_calls += 1
        self.sessions[session.id] = session
        if idempotency_key is not None:
            self.idempotency_keys[(session.tenant_id, idempotency_key)] = session.id
        return session

    async def get(self, session_id: UUID, tenant_id: str):
        # A fresh copy, deliberately -- see test_verification_session_service.py's
        # identical fake for why a real DB-backed repository never hands
        # back a live, caller-mutable reference here.
        session = self.sessions.get(session_id)
        if session is None or session.tenant_id != tenant_id:
            return None
        return session.model_copy()

    async def get_by_idempotency_key(self, tenant_id: str, idempotency_key: str):
        session_id = self.idempotency_keys.get((tenant_id, idempotency_key))
        return self.sessions.get(session_id) if session_id is not None else None

    async def list(self, tenant_id: str):
        return [s for s in self.sessions.values() if s.tenant_id == tenant_id]

    async def update(self, session: VerificationSession, *, expected_status):
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


def _active_policy(
    *, policy_id: str = "policy-standard", version: int = 1, tenant_id: str = TENANT
) -> VerificationPolicy:
    return VerificationPolicy(
        id=uuid4(),
        policy_id=policy_id,
        version=version,
        tenant_id=tenant_id,
        assurance_level=AssuranceLevel.STANDARD,
        status=PolicyStatus.ACTIVE,
        canonical_hash=f"hash-{policy_id}-v{version}",
        created_by="admin",
    )


@pytest.fixture
def policy_repo() -> FakePolicyRepository:
    return FakePolicyRepository()


@pytest.fixture
def policy_service(policy_repo) -> PolicyService:
    from core.audit.service import AuditService

    return PolicyService(policy_repo, AuditService(FakeAuditRepository()), NullSchemaCatalog())


@pytest.fixture
def session_repo() -> FakeSessionRepository:
    return FakeSessionRepository()


@pytest.mark.asyncio
async def test_create_pins_the_active_policys_id_version_and_hash(
    policy_repo, policy_service, session_repo
) -> None:
    policy = _active_policy()
    await policy_repo.add(policy)
    svc = VerificationSessionService(session_repo, policy_service, session_ttl_minutes=30)

    session = await svc.create(
        tenant_id=TENANT, external_reference=None, assurance_level=AssuranceLevel.STANDARD
    )

    assert session.policy_id == policy.policy_id
    assert session.policy_version == policy.version
    assert session.policy_hash == policy.canonical_hash


@pytest.mark.asyncio
async def test_create_raises_no_active_policy_error_and_creates_no_session(
    policy_service, session_repo
) -> None:
    """No policy has been activated for this tenant/assurance_level at
    all -- a plain creation-time failure, never an INCONCLUSIVE (there is
    no session to attach one to)."""
    svc = VerificationSessionService(session_repo, policy_service, session_ttl_minutes=30)

    with pytest.raises(NoActivePolicyError):
        await svc.create(
            tenant_id=TENANT, external_reference=None, assurance_level=AssuranceLevel.STANDARD
        )

    assert session_repo.add_calls == 0
    assert session_repo.sessions == {}


@pytest.mark.asyncio
async def test_create_without_a_policy_service_raises_runtime_error(session_repo) -> None:
    """Matches EvidenceResultService's deletion_reconciler pattern exactly:
    an unset optional dependency fails loudly and specifically when the one
    method that needs it is actually called, rather than silently skipping
    policy binding."""
    svc = VerificationSessionService(session_repo, session_ttl_minutes=30)

    with pytest.raises(RuntimeError, match="policy_service"):
        await svc.create(
            tenant_id=TENANT, external_reference=None, assurance_level=AssuranceLevel.STANDARD
        )


@pytest.mark.asyncio
async def test_a_policy_for_a_different_assurance_level_does_not_satisfy_creation(
    policy_repo, policy_service, session_repo
) -> None:
    high_assurance_policy = _active_policy().model_copy(
        update={"assurance_level": AssuranceLevel.HIGH, "id": uuid4()}
    )
    await policy_repo.add(high_assurance_policy)
    svc = VerificationSessionService(session_repo, policy_service, session_ttl_minutes=30)

    with pytest.raises(NoActivePolicyError):
        await svc.create(
            tenant_id=TENANT, external_reference=None, assurance_level=AssuranceLevel.STANDARD
        )


@pytest.mark.asyncio
async def test_idempotent_replay_returns_the_original_pin_never_re_resolved(
    policy_repo, policy_service, session_repo
) -> None:
    """Idempotency is free here (DE-002 §1): a replayed request must
    return the SAME pin the first, real attempt resolved -- even if a new
    policy version has since become active."""
    v1 = _active_policy(version=1)
    await policy_repo.add(v1)
    svc = VerificationSessionService(session_repo, policy_service, session_ttl_minutes=30)

    first = await svc.create(
        tenant_id=TENANT,
        external_reference=None,
        assurance_level=AssuranceLevel.STANDARD,
        idempotency_key="req-1",
    )
    assert first.policy_version == 1

    # a new version becomes active in between
    await policy_repo.mark_superseded(v1.id, TENANT, datetime.now(UTC))
    v2 = _active_policy(version=2)
    await policy_repo.add(v2)

    replayed = await svc.create(
        tenant_id=TENANT,
        external_reference=None,
        assurance_level=AssuranceLevel.STANDARD,
        idempotency_key="req-1",
    )

    assert replayed.id == first.id
    assert replayed.policy_version == 1  # unchanged -- never re-resolved
    assert session_repo.add_calls == 1  # the replay never reached repository.add() again


@pytest.mark.asyncio
async def test_policy_activated_after_session_creation_never_affects_that_session(
    policy_repo, policy_service, session_repo
) -> None:
    """The named adversarial property (DE-003 §16 adversarial matrix):
    'Policy v3->v4 mid-session: v3 always, regardless of v4 activation.'
    A session created while v1 is active keeps v1's pin forever, even
    after v2 supersedes it and new sessions start pinning v2."""
    v1 = _active_policy(version=1)
    await policy_repo.add(v1)
    svc = VerificationSessionService(session_repo, policy_service, session_ttl_minutes=30)

    earlier_session = await svc.create(
        tenant_id=TENANT, external_reference=None, assurance_level=AssuranceLevel.STANDARD
    )
    assert earlier_session.policy_version == 1

    await policy_repo.mark_superseded(v1.id, TENANT, datetime.now(UTC))
    v2 = _active_policy(version=2)
    await policy_repo.add(v2)

    later_session = await svc.create(
        tenant_id=TENANT, external_reference=None, assurance_level=AssuranceLevel.STANDARD
    )

    assert earlier_session.policy_version == 1  # untouched, still v1
    assert later_session.policy_version == 2  # a true point-in-time snapshot
