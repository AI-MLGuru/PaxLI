from dataclasses import dataclass
from threading import Lock

from core.reliability.enums import CircuitState, ComponentOutcome


@dataclass(frozen=True)
class ReliabilitySnapshot:
    requests: int
    success: int
    failed: int
    timeout: int
    unavailable: int
    degraded: int
    inconclusive: int
    retries: int
    circuit_opens: int
    total_latency_ms: float

    @property
    def average_latency_ms(self) -> float:
        return self.total_latency_ms / self.requests if self.requests else 0.0


class ReliabilityMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._requests = 0
        self._outcomes = {outcome: 0 for outcome in ComponentOutcome}
        self._retries = 0
        self._circuit_opens = 0
        self._total_latency_ms = 0.0
        self._circuit_state = CircuitState.HEALTHY

    def record(self, outcome: ComponentOutcome, attempts: int, latency_ms: float) -> None:
        with self._lock:
            self._requests += 1
            self._outcomes[outcome] += 1
            self._retries += max(0, attempts - 1)
            self._total_latency_ms += latency_ms

    def record_circuit_open(self) -> None:
        with self._lock:
            self._circuit_opens += 1
            self._circuit_state = CircuitState.OPEN

    def set_circuit_state(self, state: CircuitState) -> None:
        with self._lock:
            self._circuit_state = state

    def snapshot(self) -> ReliabilitySnapshot:
        with self._lock:
            return ReliabilitySnapshot(
                requests=self._requests,
                success=self._outcomes[ComponentOutcome.SUCCESS],
                failed=self._outcomes[ComponentOutcome.FAILED],
                timeout=self._outcomes[ComponentOutcome.TIMEOUT],
                unavailable=self._outcomes[ComponentOutcome.UNAVAILABLE],
                degraded=self._outcomes[ComponentOutcome.DEGRADED],
                inconclusive=self._outcomes[ComponentOutcome.INCONCLUSIVE],
                retries=self._retries,
                circuit_opens=self._circuit_opens,
                total_latency_ms=self._total_latency_ms,
            )

    @property
    def circuit_state(self) -> CircuitState:
        with self._lock:
            return self._circuit_state