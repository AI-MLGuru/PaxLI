"""DE-003 §14's transaction boundary, transcribed exactly:

    DecisionCandidate (pure evaluator output, in memory only)
          |
    DecisionPersistenceService.persist()
          |
    INSERT DecisionResult/Provenance row  (UNIQUE(tenant_id, session_id)
          |                                is the idempotency backstop)
    REQUIRED audit event, same transaction
          |
    (commit happens at the caller's own session boundary -- this service
     never calls session.commit() itself, matching PolicyService and
     EvidenceResultService: durability is a property of the request-scoped
     unit of work, not of any single service call)

No pre-check before the insert attempt: DE-003 §14 describes exactly three
steps (insert, audit, conflict-recovery), not an optimistic existence check
first. Skipping a pre-check also means a redundant persist() call (e.g. an
orchestration retry after some earlier unrelated failure) converges through
the same single code path as a genuine concurrent race, rather than two
different paths for what is, from this service's perspective, the same
outcome -- "a decision already exists for this session."
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from core.audit.enums import AuditActorType, AuditDurability, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.decision.exceptions import DecisionAlreadyExistsError
from core.decision.models import DecisionCandidate, DecisionProvenance
from core.decision.repository import DecisionRepository

_SYSTEM_ACTOR_ID = "decision-engine"


class DecisionPersistenceService:
    """Assigns the two non-deterministic values the pure evaluator could
    not (`decision_id`, `created_at` -- see core.decision.models module
    docstring), then executes DE-003 §14's insert-then-audit sequence.

    Never calls `evaluate()` itself and never resolves a policy or fetches
    evidence -- this service's only input is an already-produced
    DecisionCandidate. What calls the evaluator and what happens when the
    evaluator itself raises is the evaluation orchestration boundary
    (DE-004 Phase 4), deliberately out of scope here.
    """

    def __init__(self, repository: DecisionRepository, audit_service: AuditService) -> None:
        self.repository = repository
        self.audit_service = audit_service

    async def persist(
        self,
        candidate: DecisionCandidate,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> DecisionProvenance:
        """Idempotent under DE-003 §14 step 5: a retry after an earlier
        required-audit failure (which rolls back the whole attempt --
        see the failure-path integration test) re-runs this method and
        either completes cleanly (no row survived the rollback) or
        converges on whatever committed in the meantime via the
        DecisionAlreadyExistsError path below.
        """
        provenance = DecisionProvenance.from_candidate(
            candidate, decision_id=uuid4(), created_at=datetime.now(UTC)
        )
        try:
            saved = await self.repository.add(provenance)
        except DecisionAlreadyExistsError:
            existing = await self.repository.get_for_session(
                candidate.session_id, candidate.tenant_id
            )
            if existing is None:
                # Under READ COMMITTED, a unique-index conflict on our own
                # INSERT can only be raised once the conflicting row's
                # transaction has already committed (Postgres blocks on the
                # index entry until that resolves, rather than failing
                # early) -- so this branch should be unreachable in normal
                # operation. Surfacing the error rather than fabricating a
                # result keeps that assumption honest: DEC-5.24.1 forbids
                # masking an unresolved state as any decision outcome, and
                # returning None here would be worse than raising, since a
                # caller treating None as "no decision was ever produced"
                # would be silently wrong. Re-raising lets a retry converge
                # through this same method (§14 step 5).
                raise
            # A concurrent evaluation of the same session won the race.
            # This is success, not this attempt's failure -- the winner's
            # own DECISION_PRODUCED audit event already covers "a decision
            # was produced for this session," so nothing new is recorded
            # here.
            return existing

        await self.audit_service.record(
            tenant_id=saved.tenant_id,
            session_id=saved.session_id,
            event_type=AuditEventType.DECISION_PRODUCED,
            component="decision",
            action="produce",
            status=AuditStatus.SUCCESS,
            actor_type=AuditActorType.SYSTEM,
            actor_id=_SYSTEM_ACTOR_ID,
            request_id=request_id,
            correlation_id=correlation_id,
            metadata={
                "decision_id": str(saved.decision_id),
                "outcome": saved.outcome.value,
                "reason_codes": list(saved.reason_codes),
                "policy_id": saved.policy_reference.policy_id,
                "policy_version": saved.policy_reference.policy_version,
                "evaluation_reason": saved.evaluation_reason.value,
            },
            dedupe_key=f"decision-produced:{saved.decision_id}",
            durability=AuditDurability.REQUIRED,
        )
        return saved

    async def get(self, *, decision_id: UUID, tenant_id: str) -> DecisionProvenance | None:
        return await self.repository.get(decision_id, tenant_id)

    async def get_for_session(
        self, *, session_id: UUID, tenant_id: str
    ) -> DecisionProvenance | None:
        return await self.repository.get_for_session(session_id, tenant_id)
