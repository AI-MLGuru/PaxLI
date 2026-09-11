"""DE-003 §11 / Amendment B: the defensive fallback for duplicate effective
evidence. The primary invariant is the database's own partial unique index
(ix_evidence_results_one_effective_per_type); this module exists only for
the case that invariant is somehow bypassed (a bug, a manual DB edit, a
migration window) -- it must never be the normal path.
"""

import logging
from collections.abc import Sequence

from core.evidence_result.models import EvidenceResult

logger = logging.getLogger(__name__)


def resolve_one_effective_per_type(
    results: Sequence[EvidenceResult],
) -> list[EvidenceResult]:
    """Groups `results` by evidence_type and returns exactly one per type.

    Deterministic tie-break (Amendment B, not left as "most recent wins"
    without a total order): `produced_at` descending, then `id` descending
    as the immutable final tie-breaker -- two rows can share a
    `produced_at` timestamp, but never the same id. Emits a warning-level
    observability signal whenever more than one candidate is found for a
    type: the primary invariant should make this unreachable in practice,
    so its occurrence is itself an integrity signal worth surfacing, not a
    silently-normalized routine case.
    """
    by_type: dict[str, list[EvidenceResult]] = {}
    for result in results:
        by_type.setdefault(result.evidence_type.value, []).append(result)

    resolved: list[EvidenceResult] = []
    for evidence_type, candidates in by_type.items():
        if len(candidates) > 1:
            logger.warning(
                "duplicate_effective_evidence_detected",
                extra={
                    "evidence_type": evidence_type,
                    "candidate_ids": [str(c.id) for c in candidates],
                    "session_id": str(candidates[0].session_id),
                    "tenant_id": candidates[0].tenant_id,
                },
            )
        winner = max(candidates, key=lambda r: (r.produced_at, r.id))
        resolved.append(winner)
    return resolved
