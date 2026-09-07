from collections.abc import Awaitable, Callable
from time import monotonic
from typing import TypeVar

from core.reliability.enums import CircuitState
from core.reliability.metrics import ReliabilityMetrics

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    pass


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 30.0,
        clock: Callable[[], float] = monotonic,
        metrics: ReliabilityMetrics | None = None,
    ) -> None:
        if failure_threshold < 1 or recovery_timeout_seconds <= 0:
            raise ValueError("invalid circuit breaker configuration")
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.clock = clock
        self.state = CircuitState.HEALTHY
        self.failure_count = 0
        self.opened_at: float | None = None
        self.metrics = metrics

    def allow_request(self) -> bool:
        if self.state != CircuitState.OPEN:
            return True
        if (
            self.opened_at is not None
            and self.clock() - self.opened_at >= self.recovery_timeout_seconds
        ):
            self.state = CircuitState.RECOVERY
            if self.metrics is not None:
                self.metrics.set_circuit_state(self.state)
            return True
        return False

    def record_success(self) -> None:
        self.failure_count = 0
        self.opened_at = None
        self.state = CircuitState.HEALTHY
        if self.metrics is not None:
            self.metrics.set_circuit_state(self.state)

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = self.clock()
            if self.metrics is not None:
                self.metrics.record_circuit_open()

    async def call(self, operation: Callable[[], Awaitable[T]]) -> T:
        if not self.allow_request():
            raise CircuitOpenError("Circuit breaker is open")
        try:
            result = await operation()
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result
