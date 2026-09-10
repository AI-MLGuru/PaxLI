"""Real PostgreSQL integration tests for Foundation-010 (Rate Limiting /
Abuse Prevention) Phase 2. Skipped when Postgres isn't reachable, mirroring
tests/integration/test_policy_persistence.py's pattern -- including its
barrier-synchronized concurrency methodology (a naive asyncio.gather() of
several full check_and_consume() calls is not reliable proof by itself;
see that file's own docstring for why).
"""

import asyncio
import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.averiq_api.config import get_settings
from core.rate_limit.enums import RateLimitScope
from core.rate_limit.exceptions import RateLimiterUnavailableError
from core.rate_limit.models import RateLimitRule
from infrastructure.database.models.rate_limit_window import RateLimitWindowRecord
from infrastructure.database.session import session_factory
from infrastructure.rate_limit.postgres_limiter import PostgresRateLimiter
from infrastructure.rate_limit.pruning import prune_expired_windows


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


async def _cleanup(scope_key: str) -> None:
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(RateLimitWindowRecord).where(
                        RateLimitWindowRecord.scope_key == scope_key
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            await session.delete(row)
        await session.commit()


async def test_single_check_and_consume_allows_and_increments() -> None:
    scope_key = f"test|single|{uuid4()}"
    limiter = PostgresRateLimiter(session_factory)
    rule = RateLimitRule(scope=RateLimitScope.OPERATION, limit=5, window_seconds=60)

    decision = await limiter.check_and_consume(scope_key, rule)

    assert decision.allowed is True
    assert decision.remaining == 4
    await _cleanup(scope_key)


async def test_exceeding_the_limit_within_a_window_is_rejected() -> None:
    scope_key = f"test|exceed|{uuid4()}"
    limiter = PostgresRateLimiter(session_factory)
    rule = RateLimitRule(scope=RateLimitScope.OPERATION, limit=2, window_seconds=60)

    first = await limiter.check_and_consume(scope_key, rule)
    second = await limiter.check_and_consume(scope_key, rule)
    third = await limiter.check_and_consume(scope_key, rule)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.retry_after_seconds > 0
    await _cleanup(scope_key)


async def test_admission_survives_the_caller_own_transaction_rolling_back() -> None:
    """The durability property: PostgresRateLimiter commits its own,
    independent transaction. A caller that consumes a slot and then rolls
    back its OWN unrelated business transaction must not undo the
    increment -- otherwise an attacker could retry a failed operation
    without ever consuming allowance."""
    scope_key = f"test|durable|{uuid4()}"
    limiter = PostgresRateLimiter(session_factory)
    rule = RateLimitRule(scope=RateLimitScope.OPERATION, limit=5, window_seconds=60)

    async with session_factory() as caller_session:
        # Simulate a request: consume a slot, then the request's own
        # business logic fails and the caller rolls back ITS session.
        # PostgresRateLimiter never touches caller_session at all.
        decision = await limiter.check_and_consume(scope_key, rule)
        assert decision.allowed is True
        await caller_session.rollback()

    async with session_factory() as verify_session:
        row = (
            await verify_session.execute(
                select(RateLimitWindowRecord).where(RateLimitWindowRecord.scope_key == scope_key)
            )
        ).scalar_one()
        assert row.count == 1  # the increment is durable despite the caller's rollback
    await _cleanup(scope_key)


async def test_an_old_window_does_not_affect_the_current_window() -> None:
    """Temporal isolation: a stale row already at its limit for a PAST
    window must not affect admission for the CURRENT window -- each
    (scope_key, window_start) pair is its own independent counter."""
    scope_key = f"test|isolation|{uuid4()}"
    rule = RateLimitRule(scope=RateLimitScope.OPERATION, limit=1, window_seconds=60)
    stale_window_start = datetime.now(UTC) - timedelta(hours=2)

    async with session_factory() as session:
        session.add(
            RateLimitWindowRecord(scope_key=scope_key, window_start=stale_window_start, count=999)
        )
        await session.commit()

    limiter = PostgresRateLimiter(session_factory)
    decision = await limiter.check_and_consume(scope_key, rule)

    assert decision.allowed is True  # the current window is fresh, unaffected by the stale row
    await _cleanup(scope_key)


async def test_pruning_removes_only_expired_windows() -> None:
    scope_key = f"test|prune|{uuid4()}"
    stale_window_start = datetime.now(UTC) - timedelta(hours=48)

    async with session_factory() as session:
        session.add(
            RateLimitWindowRecord(scope_key=scope_key, window_start=stale_window_start, count=3)
        )
        await session.commit()

    limiter = PostgresRateLimiter(session_factory)
    rule = RateLimitRule(scope=RateLimitScope.OPERATION, limit=5, window_seconds=60)
    await limiter.check_and_consume(scope_key, rule)  # a fresh, current-window row

    deleted = await prune_expired_windows(session_factory, retention=timedelta(hours=24))
    assert deleted >= 1

    async with session_factory() as session:
        remaining = (
            (
                await session.execute(
                    select(RateLimitWindowRecord).where(
                        RateLimitWindowRecord.scope_key == scope_key
                    )
                )
            )
            .scalars()
            .all()
        )
        # the stale row is gone; the current-window row survives
        assert len(remaining) == 1
        assert remaining[0].window_start > stale_window_start
    await _cleanup(scope_key)


async def test_pruner_failure_or_absence_does_not_affect_admission() -> None:
    """Pruner independence: admission correctness must not depend on the
    pruner having run. This test never calls prune_expired_windows() at
    all, and admission still behaves correctly against an un-pruned
    table."""
    scope_key = f"test|prune-independence|{uuid4()}"
    limiter = PostgresRateLimiter(session_factory)
    rule = RateLimitRule(scope=RateLimitScope.OPERATION, limit=1, window_seconds=60)

    first = await limiter.check_and_consume(scope_key, rule)
    second = await limiter.check_and_consume(scope_key, rule)

    assert first.allowed is True
    assert second.allowed is False
    await _cleanup(scope_key)


async def test_limiter_unavailable_error_on_unreachable_database() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    unreachable_engine = create_async_engine(
        "postgresql+asyncpg://averiq:averiq@127.0.0.1:59999/averiq",
        pool_pre_ping=False,
    )
    unreachable_session_factory = async_sessionmaker(unreachable_engine, expire_on_commit=False)
    limiter = PostgresRateLimiter(unreachable_session_factory)
    rule = RateLimitRule(scope=RateLimitScope.OPERATION, limit=5, window_seconds=60)

    with pytest.raises(RateLimiterUnavailableError):
        await limiter.check_and_consume("test|unreachable", rule)
    await unreachable_engine.dispose()


async def test_concurrent_contention_admits_at_most_the_limit() -> None:
    """The decisive invariant: for one (scope_key, window_start) and limit
    L, under genuine concurrent contention, at most L calls are admitted,
    and every admitted call corresponds to exactly one durable counter
    increment. Same barrier-synchronized methodology as Foundation-009's
    concurrent-activation test -- a plain asyncio.gather() of N full
    check_and_consume() calls is not sufficient by itself; PostgresRateLimiter
    opens a genuinely new connection/transaction per call, so N real
    concurrent connections are required to prove the atomic upsert (not
    Python scheduling) is what resolves the race.

    concurrency is deliberately kept well under the shared engine's
    connection pool capacity (default pool_size=5 + max_overflow=10 = 15,
    infrastructure/database/session.py). A first version of this test used
    concurrency=20 and produced a genuine finding, not a flaky test: tasks
    queued behind pool exhaustion exceeded CHECK_TIMEOUT_SECONDS waiting for
    a connection, which is pool-sizing/backpressure behavior -- a real
    concern, but a different one from the atomicity invariant this test
    exists to prove. 8 concurrent attempts against a limit of 3 is enough
    genuine overlap to prove the invariant without that confound.
    """
    scope_key = f"test|concurrency|{uuid4()}"
    limiter = PostgresRateLimiter(session_factory)
    limit = 3
    concurrency = 8
    rule = RateLimitRule(scope=RateLimitScope.OPERATION, limit=limit, window_seconds=60)

    barrier_released = asyncio.Event()

    async def _attempt() -> bool:
        await barrier_released.wait()
        decision = await limiter.check_and_consume(scope_key, rule)
        return decision.allowed

    tasks = [asyncio.create_task(_attempt()) for _ in range(concurrency)]
    # give every task a chance to reach the barrier before releasing them
    # together, so their check_and_consume() calls genuinely race against
    # each other rather than running one after another.
    await asyncio.sleep(0.05)
    barrier_released.set()
    results = await asyncio.gather(*tasks)

    admitted = sum(1 for allowed in results if allowed)
    rejected = sum(1 for allowed in results if not allowed)
    assert admitted == limit
    assert rejected == concurrency - limit

    async with session_factory() as session:
        row = (
            await session.execute(
                select(RateLimitWindowRecord).where(RateLimitWindowRecord.scope_key == scope_key)
            )
        ).scalar_one()
        # every attempt -- admitted or rejected -- is one durable increment;
        # count reflects all `concurrency` attempts, never fewer (a lost
        # update) and never more (a double-count).
        assert row.count == concurrency
    await _cleanup(scope_key)
