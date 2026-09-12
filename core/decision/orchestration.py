"""DE-004 Phase 4: the evaluation orchestration boundary.

DE-003 §13 deliberately left this out of the Decision Engine's own
contract: "What drives CREATED -> PROCESSING, and what calls the
evaluator, remains explicitly out of scope here... DE-003 only fixes the
evaluator's own contract: given a DecisionEvaluationContext, produce
exactly one DecisionResult, once, ever, per session." This module is that
missing connector -- and nothing more:

    Session (with its DE-002/DE-003 §1 pin)
          |
    resolve the pinned policy, verify its hash               <- DE-002 §8 step 1
          |
    resolve effective evidence
          |
    DecisionEvaluationContext
          |
    evaluate()                     <- the pure evaluator (core.decision.evaluator)
          |
    DecisionCandidate
          |
    DecisionPersistenceService.persist()     <- Phase 3
          |
    DecisionProvenance

Deliberately excluded, matching the diagram above exactly (not touching
anything the diagram doesn't show):

- What triggers this at all (CREATED -> PROCESSING, a webhook, a poll, a
  worker) -- out of scope per DE-003 §13, unchanged.
- Any change to VerificationSession.status as a result of the decision.
  DEC-5.3's state-separation principle keeps session lifecycle and final
  decision as genuinely independent dimensions; whether/how a session's
  lifecycle status should ever be synchronized to a decision outcome is a
  Part IV workflow-integration question that has not been through the
  DE-00X reconciliation process at all, and building it here without that
  reconciliation would be inventing behavior, not connecting an existing
  pipeline. Reported explicitly, not silently decided either way.
"""

import logging
from uuid import UUID

from core.audit.enums import AuditActorType, AuditDurability, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.decision.context import DecisionEvaluationContext
from core.decision.enums import DecisionOutcome, EngineReasonCode, EvaluationReason
from core.decision.evaluator import evaluate
from core.decision.models import DecisionCandidate, DecisionProvenance
from core.decision.persistence import DecisionPersistenceService
from core.decision.references import PolicyReference
from core.evidence_result.service import EvidenceResultService
from core.policy.service import PolicyService
from core.verification.service import VerificationSessionService

logger = logging.getLogger(__name__)

_SYSTEM_ACTOR_ID = "decision-orchestrator"


class SessionHasNoPolicyPinError(RuntimeError):
    """Raised for a session with no policy_id/policy_version/policy_hash at
    all -- structurally possible only for a row persisted before DE-004
    Phase 4's migration (VerificationSession.create() has required all
    three for every session created since). Not given an engine-level
    reason code and not turned into an INCONCLUSIVE candidate: there is no
    PolicyReference of any kind to attach to one (DEC-5.29's
    DecisionResult.policy_reference is a required field), so this is a
    precondition violation for the orchestrator's caller to handle, not a
    Decision Engine outcome."""


def _pinned_reference(
    session_policy_id: str, session_policy_version: int, session_policy_hash: str
) -> PolicyReference:
    """Built directly from the session's own pin, not from a fetched
    VerificationPolicy object -- deliberately, for the two failure paths
    below (§8 step 1) where the fetched object is either absent or not
    trustworthy. The pin is the authoritative record of what the session
    was always supposed to be evaluated against."""
    return PolicyReference(
        policy_id=session_policy_id,
        policy_version=session_policy_version,
        policy_hash=session_policy_hash,
    )


def _engine_failure_candidate(
    *,
    session_id: UUID,
    tenant_id: str,
    policy_reference: PolicyReference,
    reason_code: EngineReasonCode,
    evaluation_reason: EvaluationReason,
) -> DecisionCandidate:
    """DEC-5.24: safe failure, never VERIFIED, never an invented REJECTED --
    every context-validation failure below resolves to INCONCLUSIVE with a
    stable engine reason code."""
    return DecisionCandidate(
        session_id=session_id,
        tenant_id=tenant_id,
        outcome=DecisionOutcome.INCONCLUSIVE,
        reason_codes=(reason_code.value,),
        policy_reference=policy_reference,
        evaluation_reason=evaluation_reason,
    )


class DecisionOrchestrator:
    def __init__(
        self,
        session_service: VerificationSessionService,
        policy_service: PolicyService,
        evidence_result_service: EvidenceResultService,
        persistence_service: DecisionPersistenceService,
        audit_service: AuditService,
    ) -> None:
        self.session_service = session_service
        self.policy_service = policy_service
        self.evidence_result_service = evidence_result_service
        self.persistence_service = persistence_service
        self.audit_service = audit_service

    async def evaluate_and_persist(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        evaluation_reason: EvaluationReason = EvaluationReason.NORMAL,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> DecisionProvenance:
        """Idempotent by construction: re-invoking this for an
        already-decided session re-runs context assembly and (usually)
        evaluate(), then converges on the existing row via
        DecisionPersistenceService's own conflict-recovery path (DE-003
        §14 step 3) -- no special-casing needed here."""
        session = await self.session_service.get(session_id=session_id, tenant_id=tenant_id)

        if (
            session.policy_id is None
            or session.policy_version is None
            or session.policy_hash is None
        ):
            raise SessionHasNoPolicyPinError(
                f"session_id={session_id!s} has no policy pin -- it predates "
                "DE-004 Phase 4 and cannot be evaluated"
            )
        pinned_reference = _pinned_reference(
            session.policy_id, session.policy_version, session.policy_hash
        )

        try:
            policy = await self.policy_service.get_version(
                policy_id=session.policy_id, version=session.policy_version, tenant_id=tenant_id
            )
        except Exception:
            return await self._handle_context_read_failure(
                log_event="policy_version_read_failed",
                audit_action="read_policy_version",
                session_id=session_id,
                tenant_id=tenant_id,
                policy_id=session.policy_id,
                policy_version=session.policy_version,
                policy_reference=pinned_reference,
                reason_code=EngineReasonCode.POLICY_VERSION_UNAVAILABLE,
                evaluation_reason=evaluation_reason,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        if policy is None:
            # DE-002 §8 step 1: the pinned version cannot be re-fetched.
            # Policies are never deleted (Invariant 07), so this signals
            # genuine unavailability (e.g. a corrupted pin), not an
            # ordinary "no such policy" case.
            return await self._persist_engine_failure(
                session_id=session_id,
                tenant_id=tenant_id,
                policy_reference=pinned_reference,
                reason_code=EngineReasonCode.POLICY_VERSION_UNAVAILABLE,
                evaluation_reason=evaluation_reason,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        if policy.canonical_hash != session.policy_hash:
            # The re-fetched content's hash no longer matches what was
            # pinned -- policies are immutable once ACTIVE (Invariant 07),
            # so this can only mean the pin itself, or the stored policy
            # row, has been corrupted. Never evaluate against content that
            # cannot be verified as what the session actually pinned.
            logger.error(
                "session_policy_pin_hash_mismatch",
                extra={
                    "session_id": str(session_id),
                    "tenant_id": tenant_id,
                    "pinned_hash": session.policy_hash,
                    "fetched_hash": policy.canonical_hash,
                },
            )
            return await self._persist_engine_failure(
                session_id=session_id,
                tenant_id=tenant_id,
                policy_reference=pinned_reference,
                reason_code=EngineReasonCode.POLICY_INVALID,
                evaluation_reason=evaluation_reason,
                request_id=request_id,
                correlation_id=correlation_id,
            )

        try:
            effective_evidence = await self.evidence_result_service.list_effective_for_session(
                session_id=session_id, tenant_id=tenant_id
            )
        except Exception:
            return await self._handle_context_read_failure(
                log_event="evidence_read_failed",
                audit_action="read_effective_evidence",
                session_id=session_id,
                tenant_id=tenant_id,
                policy_id=session.policy_id,
                policy_version=session.policy_version,
                policy_reference=pinned_reference,
                reason_code=EngineReasonCode.EVIDENCE_UNAVAILABLE,
                evaluation_reason=evaluation_reason,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        context = DecisionEvaluationContext(
            session_id=session_id,
            tenant_id=tenant_id,
            policy=policy,
            effective_evidence=tuple(effective_evidence),
            evaluation_reason=evaluation_reason,
            request_id=request_id,
            correlation_id=correlation_id,
        )

        try:
            candidate = evaluate(context)
        except Exception:
            # DE-002 §12: an unhandled evaluator exception must not become
            # an implicit VERIFIED or REJECTED (DEC-5.24.1) -- caught at
            # this service boundary, converted to INCONCLUSIVE/
            # DECISION_ENGINE_ERROR, and the failure itself gets its own
            # required audit event. The evaluator is pure and touches no
            # database, so nothing about the ambient transaction is
            # poisoned by this exception the way a real IntegrityError
            # would be -- recording the failure audit in the same
            # transaction as the eventual persist() call below is safe.
            logger.error(
                "decision_engine_evaluation_failed",
                extra={"session_id": str(session_id), "tenant_id": tenant_id},
                exc_info=True,
            )
            await self.audit_service.record(
                tenant_id=tenant_id,
                session_id=session_id,
                event_type=AuditEventType.DECISION_ENGINE_FAILED,
                component="decision",
                action="evaluate",
                status=AuditStatus.FAILURE,
                actor_type=AuditActorType.SYSTEM,
                actor_id=_SYSTEM_ACTOR_ID,
                request_id=request_id,
                correlation_id=correlation_id,
                metadata={"policy_id": policy.policy_id, "policy_version": policy.version},
                durability=AuditDurability.REQUIRED,
            )
            candidate = _engine_failure_candidate(
                session_id=session_id,
                tenant_id=tenant_id,
                policy_reference=pinned_reference,
                reason_code=EngineReasonCode.DECISION_ENGINE_ERROR,
                evaluation_reason=evaluation_reason,
            )

        return await self.persistence_service.persist(
            candidate, request_id=request_id, correlation_id=correlation_id
        )

    async def get_for_session(
        self, *, session_id: UUID, tenant_id: str
    ) -> DecisionProvenance | None:
        """A pure-read passthrough to persistence_service.get_for_session()
        -- exists so WF-001 §4's PROCESSING/COMPLETED dispatch in
        VerificationWorkflowService.submit() can reach the durable
        decision through its one-way dependency on DecisionOrchestrator
        (§3's diagram), rather than the workflow layer needing its own,
        second direct dependency on DecisionPersistenceService for this
        one read."""
        return await self.persistence_service.get_for_session(
            session_id=session_id, tenant_id=tenant_id
        )

    async def _handle_context_read_failure(
        self,
        *,
        log_event: str,
        audit_action: str,
        session_id: UUID,
        tenant_id: str,
        policy_id: str | None,
        policy_version: int | None,
        policy_reference: PolicyReference,
        reason_code: EngineReasonCode,
        evaluation_reason: EvaluationReason,
        request_id: str | None,
        correlation_id: str | None,
    ) -> DecisionProvenance:
        """WF-HV-009: a genuine failure reading policy or evidence content
        during context assembly -- a DB outage, or (confirmed live) an
        EvidenceResult whose encrypted payload fails AES-GCM
        authentication, meaning its content was corrupted or tampered
        with after being written -- must resolve the same way evaluate()'s
        own exceptions already do (DEC-5.24/DEC-5.24.3): a stable engine
        reason code and a persisted INCONCLUSIVE decision, never left to
        propagate as an unhandled exception. Before this fix, such a
        failure left the session permanently stuck behind a generic 500
        with no path to any terminal outcome -- every retry hit the
        identical, non-transient failure forever.

        Deliberately NOT used for session_service.get() at the top of
        evaluate_and_persist(): at that point no PolicyReference exists
        yet to attach to a DecisionCandidate (the same reasoning already
        documented on SessionHasNoPolicyPinError -- a precondition
        violation for the caller to handle, not a Decision Engine
        outcome)."""
        logger.error(
            log_event,
            extra={"session_id": str(session_id), "tenant_id": tenant_id},
            exc_info=True,
        )
        await self.audit_service.record(
            tenant_id=tenant_id,
            session_id=session_id,
            event_type=AuditEventType.DECISION_ENGINE_FAILED,
            component="decision",
            action=audit_action,
            status=AuditStatus.FAILURE,
            actor_type=AuditActorType.SYSTEM,
            actor_id=_SYSTEM_ACTOR_ID,
            request_id=request_id,
            correlation_id=correlation_id,
            metadata={
                "reason_code": reason_code.value,
                "policy_id": policy_id,
                "policy_version": policy_version,
            },
            durability=AuditDurability.REQUIRED,
        )
        return await self._persist_engine_failure(
            session_id=session_id,
            tenant_id=tenant_id,
            policy_reference=policy_reference,
            reason_code=reason_code,
            evaluation_reason=evaluation_reason,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    async def _persist_engine_failure(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        policy_reference: PolicyReference,
        reason_code: EngineReasonCode,
        evaluation_reason: EvaluationReason,
        request_id: str | None,
        correlation_id: str | None,
    ) -> DecisionProvenance:
        candidate = DecisionCandidate(
            session_id=session_id,
            tenant_id=tenant_id,
            outcome=DecisionOutcome.INCONCLUSIVE,
            reason_codes=(reason_code.value,),
            policy_reference=policy_reference,
            evaluation_reason=evaluation_reason,
        )
        return await self.persistence_service.persist(
            candidate, request_id=request_id, correlation_id=correlation_id
        )
