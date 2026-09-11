import asyncio

import pytest

from core.reliability.circuit_breaker import CircuitBreaker, CircuitOpenError
from core.reliability.enums import CircuitState, ComponentOutcome, FailureCategory
from core.reliability.executor import execute_with_reliability
from core.reliability.health import check_dependency
from core.reliability.policies import RetryPolicy


@pytest.mark.asyncio
async def test_retry_succeeds_without_fabricating_failure() -> None:
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("temporary")
        return "evidence"

    result = await execute_with_reliability(
        operation,
        timeout_seconds=1,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0),
        category=FailureCategory.BIOMETRIC,
        timeout_code="MODEL_TIMEOUT",
        unavailable_code="MODEL_UNAVAILABLE",
        retryable_exceptions=(TimeoutError,),
        sleep=lambda _: asyncio.sleep(0),
    )

    assert result.outcome == ComponentOutcome.SUCCESS
    assert result.evidence == "evidence"
    assert result.attempts == 3


@pytest.mark.asyncio
async def test_timeout_is_distinct_from_failed_evidence() -> None:
    async def operation() -> None:
        await asyncio.sleep(0.02)

    result = await execute_with_reliability(
        operation,
        timeout_seconds=0.001,
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0),
        category=FailureCategory.BIOMETRIC,
        timeout_code="FACE_ENGINE_TIMEOUT",
        unavailable_code="FACE_ENGINE_UNAVAILABLE",
    )

    assert result.outcome == ComponentOutcome.TIMEOUT
    assert result.reason is not None
    assert result.reason.retryable is True


@pytest.mark.asyncio
async def test_non_retryable_failure_is_not_retried() -> None:
    calls = 0

    async def operation() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("invalid input")

    result = await execute_with_reliability(
        operation,
        timeout_seconds=1,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0),
        category=FailureCategory.DOCUMENT,
        timeout_code="DOCUMENT_TIMEOUT",
        unavailable_code="DOCUMENT_UNAVAILABLE",
        sleep=lambda _: asyncio.sleep(0),
    )

    assert result.outcome == ComponentOutcome.FAILED
    assert result.attempts == 1
    assert calls == 1
    assert result.reason is not None
    assert result.reason.retryable is False


@pytest.mark.asyncio
async def test_retryable_exception_exhausted_becomes_unavailable_not_failed() -> None:
    """The one outcome case the other tests in this file don't already
    cover directly: a *retryable* exception (ConnectionError, in the
    default retryable_exceptions tuple) that never succeeds within the
    retry budget must resolve to UNAVAILABLE, not FAILED -- WF-001 §14 /
    DEC-5.23.2's "infrastructure failure must not become an invented
    rejection" applies at this layer too: UNAVAILABLE and FAILED carry
    different retryability semantics (see result.reason.retryable below),
    and conflating them would misdescribe a transient dependency outage as
    a definitive failure.

    Deliberately exercises execute_with_reliability() directly, with no
    VerificationSession or workflow orchestrator involved -- WF-001 §14's
    disposition for the deleted core/verification/orchestrator.py
    scaffold: this reliability mechanism is tested on its own terms, not
    through a class that mutated session lifecycle state as a side effect
    of retry/circuit-breaker plumbing."""

    async def unavailable() -> None:
        raise ConnectionError("provider offline")

    result = await execute_with_reliability(
        unavailable,
        timeout_seconds=1,
        retry_policy=RetryPolicy(max_attempts=1),
        category=FailureCategory.EXTERNAL_PROVIDER,
        timeout_code="PROVIDER_TIMEOUT",
        unavailable_code="PROVIDER_UNAVAILABLE",
    )

    assert result.outcome == ComponentOutcome.UNAVAILABLE
    assert result.reason is not None
    assert result.reason.retryable is True


@pytest.mark.asyncio
async def test_circuit_breaker_opens_and_recovers() -> None:
    now = 0.0
    breaker: CircuitBreaker = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_seconds=10,
        clock=lambda: now,
    )

    async def fail() -> None:
        raise RuntimeError("down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.call(fail)
    assert breaker.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        await breaker.call(fail)
    now = 10.0
    assert breaker.allow_request() is True
    breaker.record_success()
    assert breaker.state.value == CircuitState.HEALTHY.value


@pytest.mark.asyncio
async def test_dependency_health_returns_unavailable_without_raising() -> None:
    async def check() -> None:
        raise ConnectionError("database offline")

    health = await check_dependency("database", check)

    assert health.outcome == ComponentOutcome.UNAVAILABLE
    assert health.component == "database"
