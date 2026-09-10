"""Private execution plumbing shared by postgres_policies.py and
minio_policies.py.

This is NOT a generic "call anything" dependency guard -- every call site in
those two modules still names its own dependency, operation, timeout, and
retry policy explicitly. This only avoids duplicating the
circuit-breaker-check -> execute -> record -> log sequence twice.
"""

from collections.abc import Awaitable, Callable
from time import monotonic

from core.reliability.circuit_breaker import CircuitBreaker
from core.reliability.enums import ComponentOutcome, FailureCategory
from core.reliability.executor import execute_with_reliability
from core.reliability.metrics import ReliabilityMetrics
from core.reliability.models import ComponentResult, FailureReason
from core.reliability.policies import RetryPolicy
from infrastructure.observability.reliability_logging import log_dependency_call


async def run_guarded[T](
    operation: Callable[[], Awaitable[T]],
    *,
    dependency: str,
    operation_name: str,
    timeout_seconds: float,
    retry_policy: RetryPolicy,
    breaker: CircuitBreaker,
    metrics: ReliabilityMetrics,
) -> ComponentResult[T]:
    if not breaker.allow_request():
        result: ComponentResult[T] = ComponentResult(
            ComponentOutcome.UNAVAILABLE,
            reason=FailureReason(
                f"{dependency.upper()}_CIRCUIT_OPEN",
                FailureCategory.INFRASTRUCTURE,
                f"{dependency} circuit breaker is open",
                retryable=True,
            ),
        )
        log_dependency_call(
            dependency=dependency, operation=operation_name, result=result, duration_ms=0.0
        )
        return result

    started = monotonic()
    result = await execute_with_reliability(
        operation,
        timeout_seconds=timeout_seconds,
        retry_policy=retry_policy,
        category=FailureCategory.INFRASTRUCTURE,
        timeout_code=f"{dependency.upper()}_{operation_name.upper()}_TIMEOUT",
        unavailable_code=f"{dependency.upper()}_{operation_name.upper()}_UNAVAILABLE",
        metrics=metrics,
    )
    duration_ms = (monotonic() - started) * 1000

    if result.successful:
        breaker.record_success()
    else:
        breaker.record_failure()

    log_dependency_call(
        dependency=dependency, operation=operation_name, result=result, duration_ms=duration_ms
    )
    return result
