from collections.abc import Awaitable, Callable

from core.reliability.circuit_breaker import CircuitBreaker, CircuitOpenError
from core.reliability.enums import ComponentOutcome, FailureCategory
from core.reliability.executor import execute_with_reliability
from core.reliability.metrics import ReliabilityMetrics
from core.reliability.models import ComponentResult, FailureReason
from core.reliability.policies import RetryPolicy
from core.verification.enums import VerificationStatus
from core.verification.models import VerificationSession


class VerificationOrchestrator:
    """Coordinates verification engines without owning their implementation details."""

    async def process(self, session: VerificationSession) -> VerificationSession:
        if session.status == VerificationStatus.CREATED:
            session.transition_to(VerificationStatus.PROCESSING)
        return session

    async def process_component(
        self,
        session: VerificationSession,
        operation: Callable[[], Awaitable[object]],
        *,
        category: FailureCategory,
        timeout_seconds: float = 5.0,
        retry_policy: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        metrics: ReliabilityMetrics | None = None,
    ) -> ComponentResult[object]:
        """Run one engine safely; dependency failure never becomes a rejection."""
        await self.process(session)
        policy = retry_policy or RetryPolicy()
        result: ComponentResult[object]
        if circuit_breaker is not None and not circuit_breaker.allow_request():
            if metrics is not None:
                metrics.record_circuit_open()
            result = ComponentResult[object](
                ComponentOutcome.UNAVAILABLE,
                reason=FailureReason(
                    "DEPENDENCY_CIRCUIT_OPEN",
                    category,
                    "Dependency circuit breaker is open",
                    retryable=True,
                ),
            )
        else:
            try:
                result = await execute_with_reliability(
                    operation,
                    timeout_seconds=timeout_seconds,
                    retry_policy=policy,
                    category=category,
                    timeout_code="DEPENDENCY_TIMEOUT",
                    unavailable_code="DEPENDENCY_UNAVAILABLE",
                    metrics=metrics,
                )
            except CircuitOpenError:
                result = ComponentResult[object](
                    ComponentOutcome.UNAVAILABLE,
                    reason=FailureReason(
                        "DEPENDENCY_CIRCUIT_OPEN",
                        category,
                        "Dependency circuit breaker is open",
                        retryable=True,
                    ),
                )
        if circuit_breaker is not None:
            if result.successful:
                circuit_breaker.record_success()
            elif result.outcome in {
                ComponentOutcome.FAILED,
                ComponentOutcome.TIMEOUT,
                ComponentOutcome.UNAVAILABLE,
            }:
                circuit_breaker.record_failure()
        if not result.successful and session.status == VerificationStatus.PROCESSING:
            session.transition_to(VerificationStatus.INCONCLUSIVE)
        return result
