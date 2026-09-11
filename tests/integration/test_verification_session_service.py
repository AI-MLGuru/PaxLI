"""Real PostgreSQL integration tests for WF-001 §11's compare-and-swap
lifecycle transition, under a genuine concurrent race -- not merely
against fakes. Skipped when Postgres isn't reachable, mirroring
tests/integration/test_evidence_result_persistence.py's pattern.
"""

import asyncio
import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest

from apps.api.paxli_api.config import get_settings
from core.verification.enums import VerificationStatus
from core.verification.exceptions import ConcurrentTransitionError, SessionAlreadyTerminalError
from core.verification.service import VerificationSessionService
from infrastructure.database.models.verification_session import VerificationSessionRecord
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


async def _create_session_in_status(tenant_id: str, status: VerificationStatus) -> UUID:
    session_id = uuid4()
    async with session_factory() as session:
        session.add(
            VerificationSessionRecord(
                id=str(session_id),
                tenant_id=tenant_id,
                status=status.value,
                assurance_level="STANDARD",
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await session.commit()
    return session_id


async def test_concurrent_cancellation_one_wins_one_observes_a_conflict() -> None:
    """WF-001 §11: two requests racing to cancel the same PROCESSING
    session. The database's row lock on the CAS UPDATE resolves the race,
    never an application-level check-then-write.

    Same barrier-synchronized methodology as
    test_policy_persistence.py's concurrent-activation test -- a plain
    asyncio.gather is not reliable proof by itself (a fast local Postgres
    can let one coroutine finish before the other's first await is even
    scheduled), so an asyncio.Event forces the second attempt's UPDATE to
    genuinely block on the first's still-open, uncommitted row lock.
    """
    tenant_id = f"tenant-cas-race-{uuid4()}"
    session_id = await _create_session_in_status(tenant_id, VerificationStatus.PROCESSING)
    first_cancelled = asyncio.Event()

    async def _cancel_attempt(*, wait_for_signal: bool, delay_before_commit: float) -> str:
        async with session_factory() as session:
            service = VerificationSessionService(SqlAlchemyVerificationSessionRepository(session))
            if wait_for_signal:
                await first_cancelled.wait()
            try:
                try:
                    await service.cancel(session_id=session_id, tenant_id=tenant_id)
                except ConcurrentTransitionError:
                    await session.rollback()
                    return "conflict"
            finally:
                if not wait_for_signal:
                    first_cancelled.set()
            if delay_before_commit:
                await asyncio.sleep(delay_before_commit)
            await session.commit()
            return "won"

    results = await asyncio.gather(
        _cancel_attempt(wait_for_signal=False, delay_before_commit=0.5),
        _cancel_attempt(wait_for_signal=True, delay_before_commit=0.0),
    )

    assert sorted(results) == ["conflict", "won"]

    async with session_factory() as verify_session:
        repo = SqlAlchemyVerificationSessionRepository(verify_session)
        final = await repo.get(session_id, tenant_id)
        assert final is not None
        assert final.status is VerificationStatus.CANCELLED  # exactly one write took effect
        assert final.completed_at is not None


async def test_cancel_of_an_already_completed_session_raises_a_named_conflict_real_postgres() -> (
    None
):
    """Finding 5's fix, against real Postgres: no bare ValueError, no
    unhandled 500 -- SessionAlreadyTerminalError, checked before the CAS
    write is even attempted."""
    tenant_id = f"tenant-cas-terminal-{uuid4()}"
    session_id = await _create_session_in_status(tenant_id, VerificationStatus.COMPLETED)

    async with session_factory() as session:
        service = VerificationSessionService(SqlAlchemyVerificationSessionRepository(session))
        with pytest.raises(SessionAlreadyTerminalError):
            await service.cancel(session_id=session_id, tenant_id=tenant_id)
        await session.rollback()
