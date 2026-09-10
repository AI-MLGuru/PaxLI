from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class RateLimitSnapshot:
    checks: int
    allowed: int
    rejected: int
    limiter_failures: int


class RateLimitMetrics:
    """Dedicated to admission-control outcomes -- deliberately not
    core.reliability.metrics.ReliabilityMetrics, whose shape (success/
    timeout/unavailable/degraded/circuit_state) is built for per-dependency
    outcomes, not per-request-scope rejection counts (Foundation-010
    discovery decision #4: a shape mismatch, not a genuine reuse)."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._checks = 0
        self._allowed = 0
        self._rejected = 0
        self._limiter_failures = 0

    def record_allowed(self) -> None:
        with self._lock:
            self._checks += 1
            self._allowed += 1

    def record_rejected(self) -> None:
        with self._lock:
            self._checks += 1
            self._rejected += 1

    def record_limiter_failure(self) -> None:
        with self._lock:
            self._limiter_failures += 1

    def snapshot(self) -> RateLimitSnapshot:
        with self._lock:
            return RateLimitSnapshot(
                checks=self._checks,
                allowed=self._allowed,
                rejected=self._rejected,
                limiter_failures=self._limiter_failures,
            )
