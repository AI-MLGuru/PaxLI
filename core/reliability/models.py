from dataclasses import dataclass, field
from typing import Any

from core.reliability.enums import ComponentOutcome, FailureCategory


@dataclass(frozen=True)
class FailureReason:
    code: str
    category: FailureCategory
    message: str
    retryable: bool


@dataclass(frozen=True)
class ComponentResult[T]:
    outcome: ComponentOutcome
    evidence: T | None = None
    reason: FailureReason | None = None
    attempts: int = 1

    @property
    def successful(self) -> bool:
        return self.outcome == ComponentOutcome.SUCCESS


@dataclass(frozen=True)
class DependencyHealth:
    component: str
    outcome: ComponentOutcome
    checked_at: float
    latency_ms: float | None = None
    detail: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
