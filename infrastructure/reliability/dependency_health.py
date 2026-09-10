"""Dependency health classification for /ready (REL-10.11, REL-10.12).

A health probe is deliberately single-shot -- it does NOT go through the
retryable policies in postgres_policies.py / minio_policies.py, since
retrying a health check adds load to a dependency that may already be
struggling (REL-10.11.3).
"""

from enum import StrEnum

from core.reliability.enums import ComponentOutcome
from core.reliability.models import DependencyHealth


class DependencyHealthState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


_OUTCOME_TO_STATE: dict[ComponentOutcome, DependencyHealthState] = {
    ComponentOutcome.SUCCESS: DependencyHealthState.HEALTHY,
    ComponentOutcome.TIMEOUT: DependencyHealthState.DEGRADED,
    ComponentOutcome.DEGRADED: DependencyHealthState.DEGRADED,
    ComponentOutcome.UNAVAILABLE: DependencyHealthState.UNAVAILABLE,
    ComponentOutcome.FAILED: DependencyHealthState.UNAVAILABLE,
    ComponentOutcome.INCONCLUSIVE: DependencyHealthState.UNKNOWN,
}

# Only HEALTHY counts as ready. This was tightened after observing real
# behavior: the MinIO SDK performs its own internal urllib3-level retries
# with backoff, so a completely unreachable MinIO (connection refused)
# doesn't fail fast -- it exceeds our health-check timeout and classifies
# as TIMEOUT/DEGRADED rather than a clean UNAVAILABLE. Readiness cannot
# distinguish "genuinely slow but working" from "down, but its own client
# library is masking that" -- REL-10.11.2 says health must not be inferred
# from process existence alone, and the safer failure direction for
# readiness specifically is to fail closed on that ambiguity.
READY_STATES = frozenset({DependencyHealthState.HEALTHY})


def classify(health: DependencyHealth) -> DependencyHealthState:
    return _OUTCOME_TO_STATE.get(health.outcome, DependencyHealthState.UNKNOWN)
