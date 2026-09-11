import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from core.audit.enums import AuditActorType, AuditDurability, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.deletion.enums import DeletionBasis
from core.deletion.exceptions import DeletionBlockedByDependentsError
from core.deletion.validation import validate_deletion_request
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.exceptions import EvidenceResultNotFoundError
from core.evidence_result.models import EvidenceResult, EvidenceResultTombstone, ModelReference
from core.evidence_result.repository import EvidenceResultRepository
from core.evidence_result.schemas import validate_result_payload

_SYSTEM_ACTOR_ID = "evidence-result-service"
_CREATE_IDEMPOTENCY_OPERATION = "evidence_result_create"


class EvidenceResultDeletionReconciler(Protocol):
    """Performs the Phase-2 (reconciliation) deletion transaction in a
    session independent of the caller's own unit of work (Invariant-06
    remediation Phase 3). Same dependency-inversion shape as
    core.evidence.service.EvidenceDeletionReconciler and
    core.policy.service.IndependentAuditRecorder."""

    async def reconcile(
        self,
        *,
        evidence_result_id: UUID,
        tenant_id: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EvidenceResultTombstone: ...


def _compute_integrity_reference(
    *,
    evidence_type: EvidenceResultType,
    status: EvidenceResultStatus,
    result: dict[str, Any] | None,
    producer: str,
    producer_version: str,
) -> str:
    canonical = json.dumps(
        {
            "evidence_type": evidence_type.value,
            "status": status.value,
            "result": result,
            "producer": producer,
            "producer_version": producer_version,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EvidenceResultService:
    """Domain service for Part III evidence results.

    Has no awareness of encryption: `result` is always a plain dict here.
    Whether and how a given evidence_type's payload is protected at rest is
    decided by the repository implementation (infrastructure layer), keyed
    off core.evidence_result.classification.classify() -- this service
    never imports core.security.keys or calls encrypt/decrypt.
    """

    def __init__(
        self,
        repository: EvidenceResultRepository,
        audit_service: AuditService,
        deletion_reconciler: EvidenceResultDeletionReconciler | None = None,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.deletion_reconciler = deletion_reconciler

    async def create(
        self,
        *,
        tenant_id: str,
        session_id: UUID,
        evidence_type: EvidenceResultType,
        status: EvidenceResultStatus,
        producer: str,
        producer_version: str,
        result: dict[str, Any] | None = None,
        reason_codes: tuple[str, ...] = (),
        score: float | None = None,
        quality: float | None = None,
        model_reference: ModelReference | None = None,
        source_reference: UUID | None = None,
        parent_evidence_result_ids: tuple[UUID, ...] = (),
        retention_until: datetime | None = None,
        idempotency_key: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EvidenceResult:
        """Raises InvalidEvidenceResultError (via validate_result_payload)
        before anything is persisted -- the caller is responsible for
        recovering with a safe INCONCLUSIVE result of its own (EVD-3.24.3);
        this method does not auto-substitute one.

        `idempotency_key`, if supplied, makes a retried submission resolve
        to the same result rather than creating a duplicate (Invariant-12
        remediation)."""
        composed_idempotency_key = (
            f"{_CREATE_IDEMPOTENCY_OPERATION}:{idempotency_key}"
            if idempotency_key is not None
            else None
        )
        if composed_idempotency_key is not None:
            existing = await self.repository.get_by_idempotency_key(
                tenant_id, session_id, composed_idempotency_key
            )
            if existing is not None:
                await self.audit_service.record(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    event_type=AuditEventType.EVIDENCE_RESULT_CREATED,
                    component="evidence_result",
                    action="create",
                    status=AuditStatus.SUCCESS,
                    actor_type=AuditActorType.SYSTEM,
                    actor_id=_SYSTEM_ACTOR_ID,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    metadata={
                        "evidence_result_id": str(existing.id),
                        "evidence_type": existing.evidence_type.value,
                        "status": existing.status.value,
                        "producer": existing.producer,
                        "idempotent_replay": True,
                    },
                    dedupe_key=f"evidence-result-created:{existing.id}",
                    durability=AuditDurability.REQUIRED,
                )
                return existing

        validate_result_payload(evidence_type, result)

        now = datetime.now(UTC)
        evidence_result = EvidenceResult(
            id=uuid4(),
            tenant_id=tenant_id,
            session_id=session_id,
            evidence_type=evidence_type,
            status=status,
            result=result,
            reason_codes=reason_codes,
            score=score,
            quality=quality,
            producer=producer,
            producer_version=producer_version,
            model_reference=model_reference,
            source_reference=source_reference,
            parent_evidence_result_ids=parent_evidence_result_ids,
            produced_at=now,
            persisted_at=now,
            integrity_reference=_compute_integrity_reference(
                evidence_type=evidence_type,
                status=status,
                result=result,
                producer=producer,
                producer_version=producer_version,
            ),
            retention_until=retention_until,
        )
        saved = await self.repository.add(evidence_result, composed_idempotency_key)
        await self.audit_service.record(
            tenant_id=tenant_id,
            session_id=session_id,
            event_type=AuditEventType.EVIDENCE_RESULT_CREATED,
            component="evidence_result",
            action="create",
            status=AuditStatus.SUCCESS,
            actor_type=AuditActorType.SYSTEM,
            actor_id=_SYSTEM_ACTOR_ID,
            request_id=request_id,
            correlation_id=correlation_id,
            metadata={
                "evidence_result_id": str(saved.id),
                "evidence_type": evidence_type.value,
                "status": status.value,
                "producer": producer,
            },
            dedupe_key=f"evidence-result-created:{saved.id}",
            durability=AuditDurability.REQUIRED,
        )
        return saved

    async def supersede(
        self,
        *,
        evidence_result_id: UUID,
        tenant_id: str,
        session_id: UUID,
        evidence_type: EvidenceResultType,
        status: EvidenceResultStatus,
        producer: str,
        producer_version: str,
        result: dict[str, Any] | None = None,
        reason_codes: tuple[str, ...] = (),
        score: float | None = None,
        quality: float | None = None,
        model_reference: ModelReference | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EvidenceResult:
        """Creates a NEW evidence result that supersedes an existing one
        (EVD-3.10.3) -- never mutates the original row's content.

        `mark_not_effective` on the original happens BEFORE `add()` of the
        new row, not after: PostgreSQL's partial unique index
        (ix_evidence_results_one_effective_per_type) is checked
        per-statement and cannot be deferred, so inserting the new
        effective row while the old one is still marked effective would
        violate the constraint immediately, even mid-transaction -- the
        exact ordering lesson already proven by PolicyService.mark_superseded
        preceding its own ACTIVE-row insert."""
        validate_result_payload(evidence_type, result)

        now = datetime.now(UTC)
        evidence_result = EvidenceResult(
            id=uuid4(),
            tenant_id=tenant_id,
            session_id=session_id,
            evidence_type=evidence_type,
            status=status,
            result=result,
            reason_codes=reason_codes,
            score=score,
            quality=quality,
            producer=producer,
            producer_version=producer_version,
            model_reference=model_reference,
            supersedes_id=evidence_result_id,
            produced_at=now,
            persisted_at=now,
            integrity_reference=_compute_integrity_reference(
                evidence_type=evidence_type,
                status=status,
                result=result,
                producer=producer,
                producer_version=producer_version,
            ),
        )
        await self.repository.mark_not_effective(evidence_result_id, tenant_id)
        saved = await self.repository.add(evidence_result)
        await self.audit_service.record(
            tenant_id=tenant_id,
            session_id=session_id,
            event_type=AuditEventType.EVIDENCE_RESULT_SUPERSEDED,
            component="evidence_result",
            action="supersede",
            status=AuditStatus.SUCCESS,
            actor_type=AuditActorType.SYSTEM,
            actor_id=_SYSTEM_ACTOR_ID,
            request_id=request_id,
            correlation_id=correlation_id,
            metadata={
                "evidence_result_id": str(saved.id),
                "supersedes_id": str(evidence_result_id),
                "evidence_type": evidence_type.value,
                "status": status.value,
            },
            durability=AuditDurability.REQUIRED,
        )
        return saved

    async def get(self, *, evidence_result_id: UUID, tenant_id: str) -> EvidenceResult | None:
        return await self.repository.get(evidence_result_id, tenant_id)

    async def list_for_session(
        self, *, session_id: UUID, tenant_id: str
    ) -> Sequence[EvidenceResult]:
        return await self.repository.list_for_session(session_id, tenant_id)

    async def request_deletion(
        self,
        *,
        evidence_result_id: UUID,
        tenant_id: str,
        deletion_basis: DeletionBasis,
        basis_reference: str | None,
        authorized_by: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EvidenceResultTombstone:
        """Phase-1 (request) transaction -- see
        core.evidence.service.EvidenceService.request_deletion for the full
        rationale (identical shape, applied to an interpreted result rather
        than a raw capture)."""
        validate_deletion_request(
            deletion_basis=deletion_basis,
            basis_reference=basis_reference,
            authorized_by=authorized_by,
        )

        existing_tombstone = await self.repository.get_tombstone(evidence_result_id, tenant_id)
        if existing_tombstone is not None:
            return existing_tombstone

        evidence_result = await self.repository.get(evidence_result_id, tenant_id)
        if evidence_result is None:
            raise EvidenceResultNotFoundError(
                f"no evidence_result_id={evidence_result_id!s} for this tenant to delete"
            )
        if await self.repository.has_dependent_evidence_results(evidence_result_id, tenant_id):
            raise DeletionBlockedByDependentsError(
                f"evidence_result_id={evidence_result_id!s} has a dependent "
                "EvidenceResult (supersedes_id) -- delete the dependent result(s) first"
            )

        tombstone = EvidenceResultTombstone(
            evidence_result_id=evidence_result_id,
            session_id=evidence_result.session_id,
            tenant_id=tenant_id,
            deletion_basis=deletion_basis,
            basis_reference=basis_reference,
            authorized_by=authorized_by,
            evidence_integrity_reference=evidence_result.integrity_reference,
        )
        saved = await self.repository.add_tombstone(tombstone)
        await self.audit_service.record(
            tenant_id=tenant_id,
            session_id=evidence_result.session_id,
            event_type=AuditEventType.EVIDENCE_RESULT_DELETION_REQUESTED,
            component="evidence_result",
            action="request_deletion",
            status=AuditStatus.SUCCESS,
            actor_type=AuditActorType.CLIENT,
            actor_id=authorized_by,
            request_id=request_id,
            correlation_id=correlation_id,
            metadata={
                "evidence_result_id": str(evidence_result_id),
                "deletion_basis": deletion_basis.value,
            },
            dedupe_key=f"evidence-result-deletion-requested:{evidence_result_id}",
            durability=AuditDurability.REQUIRED,
        )
        return saved

    async def reconcile_deletion(
        self,
        *,
        evidence_result_id: UUID,
        tenant_id: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EvidenceResultTombstone:
        """Phase-2 (reconciliation) transaction: delegates to an
        independently-committing EvidenceResultDeletionReconciler."""
        if self.deletion_reconciler is None:
            raise RuntimeError(
                "EvidenceResultService was constructed without a deletion_reconciler"
            )
        return await self.deletion_reconciler.reconcile(
            evidence_result_id=evidence_result_id,
            tenant_id=tenant_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )
