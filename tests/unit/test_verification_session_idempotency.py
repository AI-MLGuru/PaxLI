"""WF-001 §10 / WF-4.9.2-4.9.4: session-creation idempotency's canonical
fingerprint -- equivalent replay converges on the original session;
materially different reuse of the same Idempotency-Key is rejected with
IdempotencyKeyReusedError, never silently resolved to the first write.
Real-Postgres proof of the concurrent-insert race lives in
tests/integration/test_verification_session_idempotency.py; these tests
exercise the service's own comparison logic against fakes, including the
concurrent-insert recovery path via a forced conflict hook.
"""

from uuid import UUID, uuid4

import pytest

from core.policy.enums import PolicyStatus
from core.policy.models import VerificationPolicy
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel
from core.verification.exceptions import IdempotencyKeyConflictError, IdempotencyKeyReusedError
from core.verification.models import VerificationSession
from core.verification.service import VerificationSessionService

TENANT = "tenant-a"
OTHER_TENANT = "tenant-b"


class FakePolicyRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, VerificationPolicy] = {}

    async def add(self, policy: VerificationPolicy, idempotency_key: str | None = None):
        self.records[policy.id] = policy
        return policy

    async def get_by_idempotency_key(self, tenant_id, idempotency_key):
        return None

    async def mark_superseded(self, policy_row_id, tenant_id, superseded_at):
        raise NotImplementedError

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
        raise NotImplementedError

    async def get_max_version(self, policy_id, tenant_id):
        return 1

    async def list_versions(self, policy_id, tenant_id):
        return []


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


class NullSchemaCatalog:
    def is_known_evidence_type(self, evidence_type: str) -> bool:
        return True

    def supports_field(self, evidence_type: str, field: str) -> bool:
        return True


class FakeSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, VerificationSession] = {}
        self.idempotency_keys: dict[tuple[str, str], UUID] = {}
        self.add_calls = 0
        # When set, the NEXT add() call raises IdempotencyKeyConflictError
        # instead of applying its own write, and ATOMICALLY makes this
        # winner row visible via get_by_idempotency_key() at that exact
        # moment -- not before. This models the real timing of the race:
        # this attempt's own upfront get_by_idempotency_key() check (which
        # runs strictly before add()) must still see nothing, matching a
        # concurrent request that commits its equivalent row strictly
        # between that check and this attempt's own INSERT.
        self._pending_conflict_winner: VerificationSession | None = None
        # Set directly (not via seed_committed) to simulate the "should be
        # unreachable" case: add() conflicts, but no winner is ever
        # visible afterward.
        self.force_next_add_conflict_with_no_winner = False

    async def add(self, session: VerificationSession, idempotency_key: str | None = None):
        self.add_calls += 1
        if self._pending_conflict_winner is not None:
            winner = self._pending_conflict_winner
            self._pending_conflict_winner = None
            self.sessions[winner.id] = winner
            if idempotency_key is not None:
                self.idempotency_keys[(winner.tenant_id, idempotency_key)] = winner.id
            raise IdempotencyKeyConflictError("simulated concurrent insert")
        if self.force_next_add_conflict_with_no_winner:
            self.force_next_add_conflict_with_no_winner = False
            raise IdempotencyKeyConflictError("simulated concurrent insert, no winner ever visible")
        self.sessions[session.id] = session
        if idempotency_key is not None:
            self.idempotency_keys[(session.tenant_id, idempotency_key)] = session.id
        return session.model_copy()

    async def get(self, session_id: UUID, tenant_id: str):
        session = self.sessions.get(session_id)
        if session is None or session.tenant_id != tenant_id:
            return None
        return session.model_copy()

    async def get_by_idempotency_key(self, tenant_id: str, idempotency_key: str):
        session_id = self.idempotency_keys.get((tenant_id, idempotency_key))
        session = self.sessions.get(session_id) if session_id is not None else None
        return session.model_copy() if session is not None else None

    async def list(self, tenant_id: str):
        return [s for s in self.sessions.values() if s.tenant_id == tenant_id]

    async def update(self, session: VerificationSession, *, expected_status):
        raise NotImplementedError

    def stage_concurrent_winner(
        self, *, tenant_id: str, fingerprint: str
    ) -> VerificationSession:
        """The NEXT add() call will fail with IdempotencyKeyConflictError
        and, at that exact moment, make this winner row visible via
        get_by_idempotency_key() -- deliberately NOT visible before then,
        so a test using this still exercises a genuine upfront-check-sees-
        nothing-but-insert-conflicts race, not the upfront-match path."""
        session = VerificationSession(
            tenant_id=tenant_id,
            assurance_level=AssuranceLevel.STANDARD,
            fingerprint=fingerprint,
        )
        self._pending_conflict_winner = session
        return session


def _active_policy(
    *, tenant_id: str = TENANT, assurance_level: AssuranceLevel = AssuranceLevel.STANDARD
) -> VerificationPolicy:
    return VerificationPolicy(
        id=uuid4(),
        policy_id="policy-standard",
        version=1,
        tenant_id=tenant_id,
        assurance_level=assurance_level,
        status=PolicyStatus.ACTIVE,
        canonical_hash="hash-policy-standard-v1",
        created_by="admin",
    )


@pytest.fixture
def session_repo() -> FakeSessionRepository:
    return FakeSessionRepository()


@pytest.fixture
def policy_service() -> PolicyService:
    from core.audit.service import AuditService

    return PolicyService(
        FakePolicyRepository(), AuditService(FakeAuditRepository()), NullSchemaCatalog()
    )


@pytest.fixture
async def service(session_repo, policy_service) -> VerificationSessionService:
    # Both tenants get an active STANDARD policy so create() can resolve
    # one regardless of which tenant/assurance_level a given test uses.
    await policy_service.repository.add(_active_policy(tenant_id=TENANT))
    await policy_service.repository.add(_active_policy(tenant_id=OTHER_TENANT))
    return VerificationSessionService(session_repo, policy_service, session_ttl_minutes=30)


@pytest.mark.asyncio
async def test_replay_with_matching_fields_converges_on_the_original_session(
    service, session_repo
) -> None:
    first = await service.create(
        tenant_id=TENANT,
        external_reference="order-123",
        assurance_level=AssuranceLevel.STANDARD,
        idempotency_key="req-1",
    )

    replayed = await service.create(
        tenant_id=TENANT,
        external_reference="order-123",
        assurance_level=AssuranceLevel.STANDARD,
        idempotency_key="req-1",
    )

    assert replayed.id == first.id
    assert session_repo.add_calls == 1  # the replay never reached repository.add() again


@pytest.mark.asyncio
async def test_replay_with_a_different_external_reference_is_rejected(service) -> None:
    await service.create(
        tenant_id=TENANT,
        external_reference="order-123",
        assurance_level=AssuranceLevel.STANDARD,
        idempotency_key="req-1",
    )

    with pytest.raises(IdempotencyKeyReusedError):
        await service.create(
            tenant_id=TENANT,
            external_reference="order-456",  # materially different
            assurance_level=AssuranceLevel.STANDARD,
            idempotency_key="req-1",
        )


@pytest.mark.asyncio
async def test_replay_with_a_different_assurance_level_is_rejected(service) -> None:
    await service.create(
        tenant_id=TENANT,
        external_reference=None,
        assurance_level=AssuranceLevel.STANDARD,
        idempotency_key="req-1",
    )

    with pytest.raises(IdempotencyKeyReusedError):
        await service.create(
            tenant_id=TENANT,
            external_reference=None,
            assurance_level=AssuranceLevel.HIGH,  # materially different
            idempotency_key="req-1",
        )


@pytest.mark.asyncio
async def test_a_rejected_replay_creates_no_new_session(service, session_repo) -> None:
    await service.create(
        tenant_id=TENANT,
        external_reference="order-123",
        assurance_level=AssuranceLevel.STANDARD,
        idempotency_key="req-1",
    )

    with pytest.raises(IdempotencyKeyReusedError):
        await service.create(
            tenant_id=TENANT,
            external_reference="order-999",
            assurance_level=AssuranceLevel.STANDARD,
            idempotency_key="req-1",
        )

    assert session_repo.add_calls == 1  # the rejected attempt never persisted anything


@pytest.mark.asyncio
async def test_no_idempotency_key_always_creates_a_fresh_session(service) -> None:
    first = await service.create(
        tenant_id=TENANT, external_reference="order-123", assurance_level=AssuranceLevel.STANDARD
    )
    second = await service.create(
        tenant_id=TENANT, external_reference="order-123", assurance_level=AssuranceLevel.STANDARD
    )

    assert first.id != second.id


@pytest.mark.asyncio
async def test_the_same_idempotency_key_is_scoped_per_tenant(service) -> None:
    """WF-4.9.4: idempotency MUST be tenant-scoped -- two different
    tenants reusing the identical raw key value must never collide or
    converge on each other's session."""
    tenant_a_session = await service.create(
        tenant_id=TENANT,
        external_reference="order-123",
        assurance_level=AssuranceLevel.STANDARD,
        idempotency_key="shared-raw-key",
    )
    tenant_b_session = await service.create(
        tenant_id=OTHER_TENANT,
        external_reference="order-123",
        assurance_level=AssuranceLevel.STANDARD,
        idempotency_key="shared-raw-key",
    )

    assert tenant_a_session.id != tenant_b_session.id
    assert tenant_a_session.tenant_id == TENANT
    assert tenant_b_session.tenant_id == OTHER_TENANT


@pytest.mark.asyncio
async def test_concurrent_insert_conflict_recovers_by_converging_on_a_matching_winner(
    service, session_repo, policy_service
) -> None:
    """The recovery path WF-002's SAVEPOINT-adjacent mechanism exists
    for: this attempt's own upfront get_by_idempotency_key() found
    nothing (nobody had committed yet), but by the time its own
    repository.add() ran, a concurrent request had already won and
    committed an equivalent request under the same key. Recovery must
    converge on that winner, not raise."""
    from core.verification.service import _compute_session_creation_fingerprint

    fingerprint = _compute_session_creation_fingerprint(
        tenant_id=TENANT, assurance_level=AssuranceLevel.STANDARD, external_reference="order-123"
    )
    winner = session_repo.stage_concurrent_winner(tenant_id=TENANT, fingerprint=fingerprint)

    result = await service.create(
        tenant_id=TENANT,
        external_reference="order-123",
        assurance_level=AssuranceLevel.STANDARD,
        idempotency_key="req-race",
    )

    assert result.id == winner.id
    # the recovery path was genuinely exercised, not the upfront-match path
    assert session_repo.add_calls == 1


@pytest.mark.asyncio
async def test_concurrent_insert_conflict_with_a_mismatched_winner_is_rejected(
    service, session_repo
) -> None:
    """The other half of the same recovery path: the concurrent winner's
    request was materially different from this one's -- rejection must
    apply identically whether the mismatch is discovered via the upfront
    check or via this INSERT-race recovery path."""
    from core.verification.service import _compute_session_creation_fingerprint

    mismatched_fingerprint = _compute_session_creation_fingerprint(
        tenant_id=TENANT, assurance_level=AssuranceLevel.STANDARD, external_reference="order-999"
    )
    session_repo.stage_concurrent_winner(tenant_id=TENANT, fingerprint=mismatched_fingerprint)

    with pytest.raises(IdempotencyKeyReusedError):
        await service.create(
            tenant_id=TENANT,
            external_reference="order-123",
            assurance_level=AssuranceLevel.STANDARD,
            idempotency_key="req-race",
        )


@pytest.mark.asyncio
async def test_concurrent_insert_conflict_with_no_recoverable_row_reraises(
    service, session_repo
) -> None:
    """Should be unreachable in normal operation (same reasoning as
    DecisionPersistenceService.persist()'s identical branch): under
    READ COMMITTED, a unique-index conflict on our own INSERT can only be
    raised once the conflicting row's transaction has already committed,
    so the recovery fetch finding nothing is a broken assumption worth
    surfacing, never silently swallowed."""
    session_repo.force_next_add_conflict_with_no_winner = True

    with pytest.raises(IdempotencyKeyConflictError, match="no winner ever visible"):
        await service.create(
            tenant_id=TENANT,
            external_reference="order-123",
            assurance_level=AssuranceLevel.STANDARD,
            idempotency_key="req-race-orphan",
        )
