"""DP-001 Decision 3/4: the orchestration boundary between document
capture and typed, lineage-bearing EvidenceResult rows.

Defined as a Protocol, not a concrete class, because a real
implementation needs multiple independent database sessions/
transactions (DP-001 Decision 4's concurrency note: each capability
commits its own EvidenceResult independently, never sharing one
AsyncSession across concurrent calls) -- the same dependency-inversion
shape already used for EvidenceResultDeletionReconciler
(core.evidence_result.service) and IndependentAuditRecorder
(core.policy.service). core/ stays infrastructure-agnostic; the real
implementation (infrastructure.document.processor) owns its own session
lifecycle.
"""

from typing import Protocol
from uuid import UUID


class DocumentProcessor(Protocol):
    async def process(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Called unconditionally from VerificationWorkflowService.submit()'s
        PROCESSING branch (DP-001 Decision 4), before
        DecisionOrchestrator.evaluate_and_persist(). No-ops if no
        DOCUMENT-type capture exists for this session --
        REQUIRED_EVIDENCE_MISSING, if applicable, is the Decision
        Engine's concern via policy evaluation, not this method's.

        Idempotent and convergent across repeated calls (a retried
        /submit): a stage whose effective EvidenceResult is already
        reusable (PASS/FAIL/INCONCLUSIVE) is not recomputed; a
        retryable one (UNAVAILABLE) is retried and superseded on
        success.

        More than one eligible DOCUMENT capture is an explicit
        precondition failure (DP-002 reconciliation amendment,
        replacing an earlier "most recent wins" draft that invented
        selection semantics nothing had frozen): every stage resolves to
        INCONCLUSIVE with reason_code AMBIGUOUS_DOCUMENT_CAPTURE,
        checked before any capability is invoked, never resolved by an
        implicit selection rule.
        """
        ...
