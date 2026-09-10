"""Proves the retry-safety classifications from the Foundation-007
architecture decision, at the mechanism level (no real Postgres/MinIO
needed -- see tests/integration and tests/contracts/reliability for the
real-infrastructure and semantic-safety proofs).
"""

import pytest

from core.reliability.circuit_breaker import CircuitBreaker
from core.reliability.metrics import ReliabilityMetrics
from core.reliability.policies import RetryPolicy
from infrastructure.reliability._shared import run_guarded
from infrastructure.reliability.postgres_policies import (
    COMMIT_RETRY_POLICY,
    COMMIT_TIMEOUT_SECONDS,
    PostgresOperationError,
    guarded_commit,
)


class _FakeSession:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.commit_calls = 0
        self._fail_times = fail_times

    async def commit(self) -> None:
        self.commit_calls += 1
        if self.commit_calls <= self._fail_times:
            raise TimeoutError("simulated commit timeout")


@pytest.mark.asyncio
async def test_commit_is_never_auto_retried_on_timeout() -> None:
    """The core Foundation-007 safety property: an uncertain COMMIT outcome
    must not be silently resubmitted by the reliability layer itself."""
    session = _FakeSession(fail_times=99)  # always times out
    with pytest.raises(PostgresOperationError):
        await guarded_commit(session)  # type: ignore[arg-type]
    assert session.commit_calls == 1


@pytest.mark.asyncio
async def test_commit_policy_is_configured_for_zero_retries() -> None:
    assert COMMIT_RETRY_POLICY.max_attempts == 1
    assert COMMIT_TIMEOUT_SECONDS > 0


@pytest.mark.asyncio
async def test_commit_succeeds_normally() -> None:
    session = _FakeSession(fail_times=0)
    await guarded_commit(session)  # type: ignore[arg-type]
    assert session.commit_calls == 1


@pytest.mark.asyncio
async def test_read_style_operations_are_retried_when_transiently_failing() -> None:
    """Connection/read-style operations ARE safe to retry -- proven here
    against the shared executor directly with a fresh breaker/metrics pair
    (not the module-level singletons, to avoid cross-test pollution)."""
    breaker = CircuitBreaker(failure_threshold=10, recovery_timeout_seconds=30.0)
    metrics = ReliabilityMetrics()
    calls = 0

    async def flaky_read() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("transient")
        return "ok"

    result = await run_guarded(
        flaky_read,
        dependency="test",
        operation_name="read",
        timeout_seconds=1.0,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.05),
        breaker=breaker,
        metrics=metrics,
    )
    assert result.successful
    assert calls == 3


@pytest.mark.asyncio
async def test_retry_is_bounded_not_unlimited() -> None:
    breaker = CircuitBreaker(failure_threshold=10, recovery_timeout_seconds=30.0)
    metrics = ReliabilityMetrics()
    calls = 0

    async def always_fails() -> None:
        nonlocal calls
        calls += 1
        raise TimeoutError("always")

    result = await run_guarded(
        always_fails,
        dependency="test",
        operation_name="read",
        timeout_seconds=1.0,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.05),
        breaker=breaker,
        metrics=metrics,
    )
    assert not result.successful
    assert calls == 3


@pytest.mark.asyncio
async def test_circuit_breaker_short_circuits_without_calling_the_operation() -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=30.0)
    metrics = ReliabilityMetrics()
    calls = 0

    async def failing() -> None:
        nonlocal calls
        calls += 1
        raise TimeoutError("fails")

    policy = RetryPolicy(max_attempts=1)
    first = await run_guarded(
        failing,
        dependency="test",
        operation_name="op",
        timeout_seconds=1.0,
        retry_policy=policy,
        breaker=breaker,
        metrics=metrics,
    )
    assert not first.successful
    assert calls == 1

    second = await run_guarded(
        failing,
        dependency="test",
        operation_name="op",
        timeout_seconds=1.0,
        retry_policy=policy,
        breaker=breaker,
        metrics=metrics,
    )
    assert not second.successful
    assert calls == 1  # breaker is open; the operation was never invoked again
