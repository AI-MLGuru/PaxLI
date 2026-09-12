"""Real PostgreSQL integration tests for WF-001 §10's idempotency
fingerprint, under a genuine concurrent race -- not merely against fakes.
Same barrier-synchronized methodology as
tests/integration/test_verification_session_service.py's CAS race test:
a plain asyncio.gather is not reliable proof by itself (a fast local
Postgres can let one coroutine finish before the other's first await is
even scheduled), so an asyncio.Event forces the second attempt's INSERT to
genuinely block on the first's still-open, uncommitted unique-index entry.
Skipped when Postgres isn't reachable, mirroring
tests/integration/test_evidence_result_persistence.py.
"""

import asyncio
import socket
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest

from apps.api.paxli_api.config import get_settings
from core.audit.service import AuditService
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel
from core.verification.exceptions import IdempotencyKeyReusedError
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


def _session_service(session) -> VerificationSessionService:
    policy_service = PolicyService(
        SqlAlchemyVerificationPolicyRepository(session),
        AuditService(SqlAlchemyAuditEventRepository(session)),
        EvidenceResultSchemaCatalog(),
    )
    return VerificationSessionService(
        SqlAlchemyVerificationSessionRepository(session), policy_service, session_ttl_minutes=30
    )


async def _activate_policy(tenant_id: str) -> None:
    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-idempotency-race",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
        )
        await session.commit()


async def test_concurrent_creation_same_key_matching_fields_converges() -> None:
    """WF-001 §10: two requests racing to create a session under the same
    Idempotency-Key with equivalent fields. The database's unique index on
    (tenant_id, idempotency_key) resolves the race, never an
    application-level check-then-insert -- both requests must converge on
    exactly one durable row."""
    tenant_id = f"tenant-idem-match-race-{uuid4()}"
    await _activate_policy(tenant_id)
    first_started = asyncio.Event()

    async def _create_attempt(*, wait_for_signal: bool, delay_before_commit: float) -> UUID:
        async with session_factory() as session:
            service = _session_service(session)
            if wait_for_signal:
                await first_started.wait()
            try:
                result = await service.create(
                    tenant_id=tenant_id,
                    external_reference="order-race",
                    assurance_level=AssuranceLevel.STANDARD,
                    idempotency_key="req-race-match",
                )
            finally:
                if not wait_for_signal:
                    first_started.set()
            if delay_before_commit:
                await asyncio.sleep(delay_before_commit)
            await session.commit()
            return result.id

    ids = await asyncio.gather(
        _create_attempt(wait_for_signal=False, delay_before_commit=0.5),
        _create_attempt(wait_for_signal=True, delay_before_commit=0.0),
    )

    assert ids[0] == ids[1]

    async with session_factory() as verify_session:
        rows = await SqlAlchemyVerificationSessionRepository(verify_session).list(tenant_id)
        assert len(rows) == 1  # exactly one row ever persisted, despite two attempts


async def test_concurrent_creation_same_key_mismatched_fields_one_rejected() -> None:
    """The other half of the same race: the two concurrent requests
    disagree on WHAT they were creating. Whichever attempt's INSERT loses
    the database's unique-index race must recover by re-fetching the
    winner and comparing fingerprints -- discovering the mismatch and
    raising IdempotencyKeyReusedError, never silently returning the
    winner's session as if it were its own."""
    tenant_id = f"tenant-idem-mismatch-race-{uuid4()}"
    await _activate_policy(tenant_id)
    first_started = asyncio.Event()

    async def _create_attempt(
        *, external_reference: str, wait_for_signal: bool, delay_before_commit: float
    ) -> str:
        async with session_factory() as session:
            service = _session_service(session)
            if wait_for_signal:
                await first_started.wait()
            try:
                try:
                    await service.create(
                        tenant_id=tenant_id,
                        external_reference=external_reference,
                        assurance_level=AssuranceLevel.STANDARD,
                        idempotency_key="req-race-mismatch",
                    )
                except IdempotencyKeyReusedError:
                    await session.rollback()
                    return "rejected"
            finally:
                if not wait_for_signal:
                    first_started.set()
            if delay_before_commit:
                await asyncio.sleep(delay_before_commit)
            await session.commit()
            return "won"

    results = await asyncio.gather(
        _create_attempt(
            external_reference="order-A", wait_for_signal=False, delay_before_commit=0.5
        ),
        _create_attempt(
            external_reference="order-B", wait_for_signal=True, delay_before_commit=0.0
        ),
    )

    assert sorted(results) == ["rejected", "won"]

    async with session_factory() as verify_session:
        rows = await SqlAlchemyVerificationSessionRepository(verify_session).list(tenant_id)
        assert len(rows) == 1  # only the winner's row was ever persisted
        assert rows[0].external_reference == "order-A"  # the attempt that committed first
