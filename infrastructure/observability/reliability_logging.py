"""Structured events for dependency reliability (REL-10.24, REL-10.26).

Two event shapes only: a per-call event, and a periodic aggregate snapshot.
No tenant identifiers, no content, no credentials -- see the docstrings on
each function for exactly what is included.
"""

import structlog

from core.reliability.metrics import ReliabilitySnapshot
from core.reliability.models import ComponentResult

logger = structlog.get_logger("paxli.reliability")


def log_dependency_call(
    *,
    dependency: str,
    operation: str,
    result: ComponentResult[object],
    duration_ms: float,
    request_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """One structured line per guarded dependency call.

    Fields: dependency, operation, outcome, attempts, duration_ms,
    reason_code (if any), request_id, session_id (only when already
    contextually available to the caller -- never a tenant_id).
    """
    logger.info(
        "dependency_call",
        dependency=dependency,
        operation=operation,
        outcome=result.outcome.value,
        attempts=result.attempts,
        duration_ms=round(duration_ms, 2),
        reason_code=result.reason.code if result.reason else None,
        request_id=request_id,
        session_id=session_id,
    )


def log_reliability_metrics(
    *, dependency: str, snapshot: ReliabilitySnapshot, circuit_state: str
) -> None:
    """One structured line per periodic metrics snapshot for one dependency."""
    logger.info(
        "reliability_metrics",
        dependency=dependency,
        requests=snapshot.requests,
        success=snapshot.success,
        failed=snapshot.failed,
        timeout=snapshot.timeout,
        unavailable=snapshot.unavailable,
        degraded=snapshot.degraded,
        inconclusive=snapshot.inconclusive,
        retries=snapshot.retries,
        circuit_opens=snapshot.circuit_opens,
        average_latency_ms=round(snapshot.average_latency_ms, 2),
        circuit_state=circuit_state,
    )
