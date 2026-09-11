"""Real PostgreSQL integration tests for DE-004 Phase 4's session policy
pinning (DE-002/DE-003 §1 early policy binding). Skipped when Postgres
isn't reachable, mirroring tests/integration/test_evidence_result_persistence.py.
"""

import socket
from urllib.parse import urlparse

import pytest

from apps.api.averiq_api.config import get_settings
from core.audit.service import AuditService
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.policy.exceptions import NoActivePolicyError
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel
from core.verification.service import VerificationSessionService
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.policy import SqlAlchemyVerificationPolicyRepository
from infrastructure.database.repositories.verification_session import (
    SqlAlchemyVerificationSessionRepository,
)
from infrastructure.database.session import session_factory


def _postgres_reachable() -> bool:
    url = urlparse(get_settings().database_url.replace("+asyncpg", ""))
    try:
        with socket.create_connection((url.hostname, url.port or 5432), timeout=1):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.skipif(not _postgres_reachable(), reason="PostgreSQL is not reachable"),
    pytest.mark.asyncio(loop_scope="module"),
]


@pytest.fixture(scope="module", autouse=True)
async def _dispose_shared_engine_pool_after_module():
    from infrastructure.database.session import engine

    yield
    await engine.dispose()


def _services(session):
    policy_service = PolicyService(
        SqlAlchemyVerificationPolicyRepository(session),
        AuditService(SqlAlchemyAuditEventRepository(session)),
        EvidenceResultSchemaCatalog(),
    )
    session_service = VerificationSessionService(
        SqlAlchemyVerificationSessionRepository(session), policy_service, session_ttl_minutes=30
    )
    return policy_service, session_service


async def test_session_creation_pins_the_active_policy() -> None:
    tenant_id = "tenant-session-pin-basic"
    async with session_factory() as session:
        policy_service, session_service = _services(session)
        policy = await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-pin-test",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
        )
        await session.commit()

    async with session_factory() as session:
        _policy_service, session_service = _services(session)
        created = await session_service.create(
            tenant_id=tenant_id,
            external_reference=None,
            assurance_level=AssuranceLevel.STANDARD,
        )
        await session.commit()

    assert created.policy_id == policy.policy_id
    assert created.policy_version == policy.version
    assert created.policy_hash == policy.canonical_hash

    async with session_factory() as verify_session:
        fetched = await SqlAlchemyVerificationSessionRepository(verify_session).get(
            created.id, tenant_id
        )
        assert fetched is not None
        assert fetched.policy_id == policy.policy_id
        assert fetched.policy_version == policy.version
        assert fetched.policy_hash == policy.canonical_hash


async def test_session_creation_fails_when_no_policy_is_active() -> None:
    tenant_id = "tenant-session-pin-no-policy"
    async with session_factory() as session:
        _policy_service, session_service = _services(session)
        with pytest.raises(NoActivePolicyError):
            await session_service.create(
                tenant_id=tenant_id,
                external_reference=None,
                assurance_level=AssuranceLevel.STANDARD,
            )
        await session.rollback()

    async with session_factory() as verify_session:
        rows = await SqlAlchemyVerificationSessionRepository(verify_session).list(tenant_id)
        assert rows == []


async def test_policy_v2_activated_after_session_creation_never_affects_that_session() -> None:
    """DE-003 §16 adversarial matrix: 'Policy v3->v4 mid-session: v3
    always, regardless of v4 activation.' Proven here against real
    Postgres with a genuine second activation transaction, not a fake."""
    tenant_id = "tenant-session-pin-mid-session"
    async with session_factory() as session:
        policy_service, session_service = _services(session)
        v1 = await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-pin-versioned",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
        )
        await session.commit()

    async with session_factory() as session:
        _policy_service, session_service = _services(session)
        earlier_session = await session_service.create(
            tenant_id=tenant_id,
            external_reference=None,
            assurance_level=AssuranceLevel.STANDARD,
        )
        await session.commit()

    assert earlier_session.policy_version == v1.version

    async with session_factory() as session:
        policy_service, _session_service = _services(session)
        v2 = await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-pin-versioned",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
        )
        await session.commit()
    assert v2.version == v1.version + 1

    async with session_factory() as session:
        _policy_service, session_service = _services(session)
        later_session = await session_service.create(
            tenant_id=tenant_id,
            external_reference=None,
            assurance_level=AssuranceLevel.STANDARD,
        )
        await session.commit()

    async with session_factory() as verify_session:
        repo = SqlAlchemyVerificationSessionRepository(verify_session)
        refetched_earlier = await repo.get(earlier_session.id, tenant_id)
        refetched_later = await repo.get(later_session.id, tenant_id)

        assert refetched_earlier is not None
        assert refetched_earlier.policy_version == v1.version  # untouched, still v1
        assert refetched_earlier.policy_hash == v1.canonical_hash

        assert refetched_later is not None
        assert refetched_later.policy_version == v2.version  # a true point-in-time snapshot
        assert refetched_later.policy_hash == v2.canonical_hash


async def test_idempotent_replay_returns_the_original_pin_against_real_postgres() -> None:
    tenant_id = "tenant-session-pin-idempotent"
    async with session_factory() as session:
        policy_service, session_service = _services(session)
        v1 = await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-pin-idempotent",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
        )
        await session.commit()

    async with session_factory() as session:
        _policy_service, session_service = _services(session)
        first = await session_service.create(
            tenant_id=tenant_id,
            external_reference=None,
            assurance_level=AssuranceLevel.STANDARD,
            idempotency_key="req-pin-replay",
        )
        await session.commit()

    async with session_factory() as session:
        policy_service, _session_service = _services(session)
        await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-pin-idempotent",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
        )
        await session.commit()

    async with session_factory() as session:
        _policy_service, session_service = _services(session)
        replayed = await session_service.create(
            tenant_id=tenant_id,
            external_reference=None,
            assurance_level=AssuranceLevel.STANDARD,
            idempotency_key="req-pin-replay",
        )

    assert replayed.id == first.id
    assert replayed.policy_version == v1.version
