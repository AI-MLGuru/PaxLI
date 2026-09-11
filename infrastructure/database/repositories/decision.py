from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.decision.enums import DecisionOutcome, EvaluationReason
from core.decision.exceptions import DecisionAlreadyExistsError
from core.decision.models import DecisionProvenance
from core.decision.references import EvidenceReference, PolicyReference
from core.evidence_result.models import ModelReference
from infrastructure.database.models.decision import DecisionRecord


class SqlAlchemyDecisionRepository:
    """Translates a UNIQUE(tenant_id, session_id) violation into
    DecisionAlreadyExistsError -- the concrete proof that the database, not
    application logic, is the final authority on concurrent evaluation
    (DE-003 §14 step 3), same shape as
    SqlAlchemyVerificationPolicyRepository/PolicyActivationConflictError.

    Uses a SAVEPOINT (`session.begin_nested()`) around the insert attempt,
    unlike every prior IntegrityError-translating repository in this
    codebase. Those all let the conflict propagate and the caller's whole
    request-scoped session roll back (Invariant 12's per-request unit of
    work) -- correct for them, because a client-facing conflict there ends
    the request either way. DE-003 §14 step 3 asks for something the
    codebase had no precedent for: recovering *within the same call*, by
    fetching the winning row and returning it as success. Without a
    SAVEPOINT, the failed INSERT would leave the whole session's
    transaction aborted (PostgreSQL rejects every further statement,
    including a plain SELECT, until a full ROLLBACK) -- which would either
    make the recovery fetch impossible, or force discarding whatever else
    was staged earlier in the same request. The SAVEPOINT confines the
    rollback to exactly the failed insert, leaving the rest of the session
    -- and the fetch that follows -- unaffected.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, provenance: DecisionProvenance) -> DecisionProvenance:
        record = self._to_record(provenance)
        try:
            async with self.session.begin_nested():
                self.session.add(record)
                await self.session.flush()
        except IntegrityError as exception:
            raise DecisionAlreadyExistsError(
                f"a decision already exists for tenant={provenance.tenant_id!r} "
                f"session_id={provenance.session_id!s}"
            ) from exception
        return provenance

    async def get(self, decision_id: UUID, tenant_id: str) -> DecisionProvenance | None:
        record = await self.session.get(DecisionRecord, str(decision_id))
        if record is None or record.tenant_id != tenant_id:
            return None
        return self._to_domain(record)

    async def get_for_session(self, session_id: UUID, tenant_id: str) -> DecisionProvenance | None:
        statement = select(DecisionRecord).where(
            DecisionRecord.tenant_id == tenant_id,
            DecisionRecord.session_id == str(session_id),
        )
        record = (await self.session.execute(statement)).scalar_one_or_none()
        return self._to_domain(record) if record is not None else None

    def _to_record(self, provenance: DecisionProvenance) -> DecisionRecord:
        return DecisionRecord(
            id=str(provenance.decision_id),
            tenant_id=provenance.tenant_id,
            session_id=str(provenance.session_id),
            outcome=provenance.outcome.value,
            reason_codes_json=list(provenance.reason_codes),
            policy_id=provenance.policy_reference.policy_id,
            policy_version=provenance.policy_reference.policy_version,
            policy_hash=provenance.policy_reference.policy_hash,
            evidence_references_json=[
                ref.model_dump(mode="json") for ref in provenance.evidence_references
            ],
            model_references_json=[
                ref.model_dump(mode="json") for ref in provenance.model_references
            ],
            calibration_references_json=list(provenance.calibration_references),
            prohibited_types_present_json=list(provenance.prohibited_types_present),
            evaluation_reason=provenance.evaluation_reason.value,
            engine_version=provenance.engine_version,
            created_at=provenance.created_at,
        )

    def _to_domain(self, record: DecisionRecord) -> DecisionProvenance:
        return DecisionProvenance(
            decision_id=UUID(record.id),
            session_id=UUID(record.session_id),
            tenant_id=record.tenant_id,
            outcome=DecisionOutcome(record.outcome),
            reason_codes=tuple(record.reason_codes_json),
            policy_reference=PolicyReference(
                policy_id=record.policy_id,
                policy_version=record.policy_version,
                policy_hash=record.policy_hash,
            ),
            evidence_references=tuple(
                EvidenceReference.model_validate(item) for item in record.evidence_references_json
            ),
            model_references=tuple(
                ModelReference.model_validate(item) for item in record.model_references_json
            ),
            calibration_references=tuple(record.calibration_references_json),
            prohibited_types_present=tuple(record.prohibited_types_present_json),
            evaluation_reason=EvaluationReason(record.evaluation_reason),
            engine_version=record.engine_version,
            created_at=record.created_at,
        )
