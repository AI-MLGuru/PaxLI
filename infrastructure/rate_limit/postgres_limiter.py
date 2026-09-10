"""PostgreSQL-backed RateLimiterProtocol implementation (Foundation-010
Phase 2).

Only one statement matters here: a single INSERT ... ON CONFLICT DO UPDATE
... RETURNING that computes the fixed window, increments its counter, and
reports the remaining-time hint -- all server-side, all atomic, all in one
round trip. No select-then-check-then-update anywhere in this module.

This module gets its own CircuitBreaker/ReliabilityMetrics instances,
deliberately not the shared ones in infrastructure/reliability/
postgres_policies.py: a problem isolated to the rate_limit_windows table
(e.g. contention, bloat) must not trip the breaker that gates the
application's main business-transaction commits, and vice versa.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.rate_limit.exceptions import RateLimiterUnavailableError
from core.rate_limit.models import RateLimitDecision, RateLimitRule
from core.reliability.circuit_breaker import CircuitBreaker
from core.reliability.metrics import ReliabilityMetrics
from core.reliability.policies import RetryPolicy
from infrastructure.reliability._shared import run_guarded

CHECK_TIMEOUT_SECONDS = 2.0
# max_attempts=1: an uncertain outcome (timeout mid-upsert) must not be
# blindly retried -- the caller cannot tell whether the increment already
# landed, and a retry could double-count a single request. Same reasoning
# as infrastructure/reliability/postgres_policies.py's guarded_commit.
CHECK_RETRY_POLICY = RetryPolicy(max_attempts=1)

METRICS = ReliabilityMetrics()
BREAKER = CircuitBreaker(failure_threshold=5, recovery_timeout_seconds=30.0, metrics=METRICS)

_UPSERT_SQL = text("""
    INSERT INTO rate_limit_windows (scope_key, window_start, count)
    VALUES (
        :scope_key,
        to_timestamp(floor(extract(epoch from now()) / :window_seconds) * :window_seconds),
        1
    )
    ON CONFLICT (scope_key, window_start)
    DO UPDATE SET count = rate_limit_windows.count + 1
    RETURNING
        count,
        GREATEST(
            0,
            CEIL(extract(epoch from (
                window_start + make_interval(secs => :window_seconds) - now()
            )))
        )::int AS retry_after_seconds
    """)


class PostgresRateLimiter:
    """Deliberately takes a session FACTORY, never an AsyncSession -- there
    is no constructor path that could accidentally share the caller's
    request-scoped session. Every check_and_consume() call opens and
    commits its own independent transaction, so a consumed slot remains
    durable even if the caller's own business transaction later fails and
    rolls back (Foundation-010 discovery correction, proved directly in
    tests/integration/test_rate_limit_persistence.py)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def check_and_consume(self, scope_key: str, rule: RateLimitRule) -> RateLimitDecision:
        async def _do_upsert() -> tuple[int, int]:
            async with self._session_factory() as session:
                result = await session.execute(
                    _UPSERT_SQL,
                    {"scope_key": scope_key, "window_seconds": rule.window_seconds},
                )
                # positional unpacking, not row.count: Row is tuple-like, so
                # a column literally named "count" collides with tuple's
                # own builtin .count() method attribute.
                count, retry_after_seconds = result.one()
                await session.commit()
                return count, retry_after_seconds

        outcome = await run_guarded(
            _do_upsert,
            dependency="postgres_rate_limit",
            operation_name="check_and_consume",
            timeout_seconds=CHECK_TIMEOUT_SECONDS,
            retry_policy=CHECK_RETRY_POLICY,
            breaker=BREAKER,
            metrics=METRICS,
        )
        if not outcome.successful:
            message = (
                outcome.reason.message
                if outcome.reason
                else "rate limit check did not complete safely"
            )
            raise RateLimiterUnavailableError(message)

        assert outcome.evidence is not None  # successful outcomes always carry evidence
        count, retry_after_seconds = outcome.evidence
        allowed = count <= rule.limit
        return RateLimitDecision(
            allowed=allowed,
            remaining=max(0, rule.limit - count),
            retry_after_seconds=retry_after_seconds if not allowed else 0,
        )
