"""WF-001 §3-4: the verification workflow orchestration boundary.

`submit()` is the one public entry point that drives a session through
SUBMITTED, PROCESSING, and into COMPLETED, invoking the Decision Engine
through DecisionOrchestrator along the way. Dependency direction is
one-way and does not reverse (§3):

    VerificationWorkflowService
              |
              v
       DecisionOrchestrator
              |
              v
         Decision Engine

DecisionOrchestrator and everything below it remain unaware this module
exists.

PROCESSING is a recovery state, never a second public initiation path
(§4's frozen amendment): submit() dispatches on whatever status the
session is ALREADY in, rather than assuming it always starts at
CREATED/CAPTURING. A session found sitting in PROCESSING is one an
earlier submit() call left behind mid-flight (crash, timeout) --
recovered here by re-running evaluate_and_persist() (idempotent by
construction, DE-004 Phase 3/5), never by a caller deliberately choosing
PROCESSING as a starting point.
"""

from datetime import UTC, datetime
from uuid import UUID

from core.audit.enums import AuditActorType, AuditDurability, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.decision.enums import EvaluationReason
from core.decision.models import DecisionProvenance
from core.decision.orchestration import DecisionOrchestrator
from core.document.processor import DocumentProcessor
from core.face.processor import BiometricProcessor
from core.verification.enums import VerificationStatus
from core.verification.exceptions import ConcurrentTransitionError, SessionAlreadyTerminalError
from core.verification.models import VerificationSession
from core.verification.service import VerificationSessionService

_SYSTEM_ACTOR_ID = "verification-workflow"
_SYSTEM_COMPONENT = "verification_workflow"

# WF-001 §2: submit() is legal from CREATED or CAPTURING -- deliberately
# its own named constant, not a reuse of
# core.verification.enums.EVIDENCE_SUBMISSION_ALLOWED_STATUSES, even
# though the two sets currently hold identical values. They express
# different concepts (submit()-initiation eligibility vs. evidence-
# submission legality) that happen to coincide today; coupling them would
# make one silently track the other if either's membership ever changed
# for its own, unrelated reason.
_SUBMIT_INITIATION_STATUSES = (VerificationStatus.CREATED, VerificationStatus.CAPTURING)


class VerificationWorkflowService:
    def __init__(
        self,
        session_service: VerificationSessionService,
        decision_orchestrator: DecisionOrchestrator,
        audit_service: AuditService,
        document_processor: DocumentProcessor,
        biometric_processor: BiometricProcessor,
    ) -> None:
        self.session_service = session_service
        self.decision_orchestrator = decision_orchestrator
        self.audit_service = audit_service
        self.document_processor = document_processor
        self.biometric_processor = biometric_processor

    async def submit(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> tuple[VerificationSession, DecisionProvenance]:
        """WF-001 §4's dispatch, transcribed exactly: safe to call (or
        retry) from any status, because it dispatches on the session's
        CURRENT status rather than assuming where it starts.

            CREATED, CAPTURING -> transition to SUBMITTED, re-dispatch
            SUBMITTED          -> transition to PROCESSING, re-dispatch
            PROCESSING         -> evaluate (NORMAL or EXPIRATION), then
                                  transition to COMPLETED, re-dispatch
            COMPLETED          -> idempotent replay: fetch the existing
                                  decision, no new work, no new audit
            EXPIRED, CANCELLED -> SessionAlreadyTerminalError

        A `while True` loop, not a flat sequence of independent checks:
        every _advance() call can lose its CAS race to a CONCURRENT
        submit() call that raced ahead -- possibly all the way to
        COMPLETED, past whatever single hop this call was attempting.
        _advance() doesn't try to classify that outcome itself; it just
        refetches the current truth and hands it back, and the loop
        re-enters dispatch from the top on that truth, exactly as if this
        call had found the session there to begin with. A landing spot
        that matches no branch at all (EXPIRED, CANCELLED) falls through
        to the same SessionAlreadyTerminalError a fresh call would raise
        finding it there directly (WF-001 §6: the loser of a cancellation
        race translates its conflict into the appropriate error, never
        silently treats it as success).

        Raises SessionNotFoundError (via session_service.get(), tenant-
        scoped) if the session does not exist for this tenant.

        The decision returned is always present, never None: the only
        path to COMPLETED in this codebase always persists one first.
        """
        session = await self.session_service.get(session_id=session_id, tenant_id=tenant_id)
        decision: DecisionProvenance | None = None

        while True:
            if session.status in _SUBMIT_INITIATION_STATUSES:
                session = await self._advance(
                    session,
                    VerificationStatus.SUBMITTED,
                    AuditEventType.SESSION_SUBMITTED,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                continue

            if session.status is VerificationStatus.SUBMITTED:
                session = await self._advance(
                    session,
                    VerificationStatus.PROCESSING,
                    AuditEventType.SESSION_PROCESSING_STARTED,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                continue

            if session.status is VerificationStatus.PROCESSING:
                # DP-001 Decision 4: document processing runs synchronously
                # here, immediately before evaluate_and_persist() -- never
                # at evidence-capture time. Unconditional: DocumentProcessor
                # itself no-ops when no DOCUMENT-type capture exists for
                # this session.
                await self.document_processor.process(
                    session_id=session.id,
                    tenant_id=session.tenant_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                # BD-001.10 §4's frozen ordering: biometric processing runs
                # after document processing, in the same synchronous
                # PROCESSING step -- the reference side depends on
                # DOCUMENT_FIELD_EXTRACTION already being effective.
                # Unconditional, same reasoning as document_processor
                # above: BiometricProcessor itself no-ops internally when
                # no reference can be acquired and no SELFIE capture
                # exists (BD-001.7 G.2-S1/G.2-S11). No try/except here --
                # any exception propagates uncaught, exactly like
                # document_processor.process() above (BD-001.10 §6).
                await self.biometric_processor.process(
                    session_id=session.id,
                    tenant_id=session.tenant_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                # §7: PROCESSING has no EXPIRED edge -- a session past its
                # deadline is resolved only by selecting
                # EvaluationReason.EXPIRATION here, unconditionally
                # producing INCONCLUSIVE/SESSION_EXPIRED_DURING_PROCESSING
                # (the pure evaluator's own short-circuit, DE-003).
                evaluation_reason = (
                    EvaluationReason.EXPIRATION
                    if session.is_past_expiry(datetime.now(UTC))
                    else EvaluationReason.NORMAL
                )
                decision = await self.decision_orchestrator.evaluate_and_persist(
                    session_id=session.id,
                    tenant_id=session.tenant_id,
                    evaluation_reason=evaluation_reason,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                session = await self._advance(
                    session,
                    VerificationStatus.COMPLETED,
                    AuditEventType.SESSION_COMPLETED,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                continue

            if session.status is VerificationStatus.COMPLETED:
                # Idempotent replay (§4): fetch and return, no new work,
                # no new audit -- the same convergence-on-existing-result
                # pattern used throughout DE-004. `decision` is already
                # in hand if the PROCESSING branch above just produced it
                # in this same call; otherwise (a direct COMPLETED entry,
                # or a concurrent call that raced past this one) it is
                # fetched here.
                if decision is None:
                    decision = await self.decision_orchestrator.get_for_session(
                        session_id=session_id, tenant_id=tenant_id
                    )
                if decision is None:
                    # Should be unreachable -- see the docstring above.
                    # Surfacing this loudly rather than returning a
                    # silently incomplete result (DEC-5.24.1's "never
                    # mask an unresolved state" discipline, applied here
                    # too).
                    raise RuntimeError(
                        f"session_id={session_id!s} is COMPLETED but has no persisted decision"
                    )
                return session, decision

            raise SessionAlreadyTerminalError(
                f"session_id={session_id!s} is {session.status.value} and cannot be submitted"
            )

    async def _advance(
        self,
        session: VerificationSession,
        new_status: VerificationStatus,
        event_type: AuditEventType,
        *,
        request_id: str | None,
        correlation_id: str | None,
    ) -> VerificationSession:
        """One CAS transition plus its required lifecycle audit event
        (§13), same transaction, no new pattern (Invariant 12) -- shared
        by every hop submit() drives.

        A lost CAS race means some other transaction already moved this
        session on since it was last read. This method does not try to
        classify what won: it refetches the current truth and returns
        it, recording no audit (the winner's own call already recorded
        its own) -- submit()'s dispatch loop re-enters from the top on
        whatever comes back, which is the only place that needs to know
        whether that landing spot is a harmless convergence or a genuine
        conflict to raise.
        """
        from_status = session.status
        try:
            session = await self.session_service.transition(session=session, new_status=new_status)
        except ConcurrentTransitionError:
            return await self.session_service.get(
                session_id=session.id, tenant_id=session.tenant_id
            )
        await self.audit_service.record(
            tenant_id=session.tenant_id,
            session_id=session.id,
            event_type=event_type,
            component=_SYSTEM_COMPONENT,
            action="submit",
            status=AuditStatus.SUCCESS,
            actor_type=AuditActorType.SYSTEM,
            actor_id=_SYSTEM_ACTOR_ID,
            request_id=request_id,
            correlation_id=correlation_id,
            metadata={"from_status": from_status.value, "to_status": new_status.value},
            durability=AuditDurability.REQUIRED,
        )
        return session
