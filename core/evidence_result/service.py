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
from core.evidence.repository import EvidenceRepository
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.exceptions import (
    EffectiveResultAlreadyExistsError,
    EvidenceResultNotFoundError,
    InvalidProvenanceReferenceError,
    InvalidSupersessionError,
)
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
    score: float | None,
    quality: float | None,
) -> str:
    """WF-HV-009: covers every field the Decision Engine actually reads
    off an EvidenceResult -- `status`/`score`/`quality` are the three
    "universal" attributes core.decision.condition_eval._resolve_field()
    evaluates directly (everything else a condition can reference comes
    from inside `result`, already covered), so all three must be part of
    this fingerprint for EVD-3.9.2 ("integrity metadata MUST correspond
    to actual persisted content") to hold for decision-relevant content,
    not just the result payload. Before this fix, two results with
    identical status/result but different score/quality -- exactly the
    fields a threshold-based policy condition evaluates -- collided on
    an identical integrity_reference.

    Deliberately NOT extended to reason_codes/model_reference/etc.:
    condition_eval never reads them directly (confirmed by inspection of
    _resolve_field's own field list), so including them would widen this
    fingerprint's scope beyond what's demonstrably decision-relevant.

    Migration/compatibility note: this changes the resulting hash for
    every NEW EvidenceResult from this point on. integrity_reference is
    write-once (EvidenceResult has no update() path) and nothing in this
    codebase ever recomputes or re-verifies it against live content
    (confirmed: no read-time comparison exists anywhere) -- so existing
    persisted rows keep whatever value the old formula produced,
    permanently, with no code path that would notice or care about the
    formula having changed underneath them. Safe today; a future feature
    that DOES re-derive and compare integrity_reference against stored
    content would need to account for this formula's evolution (e.g. by
    keying off schema_version) rather than assuming one universal rule
    applies to every row ever written.
    """
    canonical = json.dumps(
        {
            "evidence_type": evidence_type.value,
            "status": status.value,
            "score": score,
            "quality": quality,
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
        evidence_repository: EvidenceRepository,
        deletion_reconciler: EvidenceResultDeletionReconciler | None = None,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.evidence_repository = evidence_repository
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

        validate_result_payload(evidence_type, result, parent_evidence_result_ids)
        await self._validate_provenance(
            tenant_id=tenant_id,
            session_id=session_id,
            source_reference=source_reference,
            parent_evidence_result_ids=parent_evidence_result_ids,
        )

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
                score=score,
                quality=quality,
            ),
            retention_until=retention_until,
        )
        try:
            saved = await self.repository.add(evidence_result, composed_idempotency_key)
        except EffectiveResultAlreadyExistsError:
            # A concurrent create() for the same (tenant_id, session_id,
            # evidence_type) won the race (HV-010) -- success, not this
            # attempt's failure, same DE-003 §14 philosophy as
            # DecisionPersistenceService.persist()'s identical recovery.
            # The winner's own EVIDENCE_RESULT_CREATED audit event already
            # covers "a result was produced for this type," so nothing new
            # is recorded here.
            existing = await self.get_effective_for_session_by_type(
                session_id=session_id, tenant_id=tenant_id, evidence_type=evidence_type
            )
            if existing is None:
                # Under READ COMMITTED a unique-index conflict on our own
                # INSERT can only be raised once the conflicting row's
                # transaction has already committed -- so this branch
                # should be unreachable in normal operation. Surfacing the
                # error rather than fabricating a result keeps that
                # assumption honest, matching DecisionPersistenceService.
                # persist()'s identical "should be unreachable" branch.
                raise
            return existing
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

    async def _validate_provenance(
        self,
        *,
        tenant_id: str,
        session_id: UUID,
        source_reference: UUID | None,
        parent_evidence_result_ids: tuple[UUID, ...],
    ) -> None:
        """WF-HV-009 Finding B: neither provenance field is safe to trust
        on the caller's word. `source_reference`'s DB foreign key only
        proves the Evidence row exists somewhere -- not that it belongs to
        THIS tenant/session; `parent_evidence_result_ids` has no FK at
        all. Confirmed live before this check existed: a caller in one
        tenant could create a result that falsely claims derivation from
        another tenant's evidence or results, with no error and no
        signal that the lineage is forged."""
        if source_reference is not None:
            source = await self.evidence_repository.get(source_reference, tenant_id)
            if source is None or source.session_id != session_id:
                raise InvalidProvenanceReferenceError(
                    f"source_reference={source_reference!s} is not a "
                    f"session_id={session_id!s} evidence capture in this tenant"
                )
        for parent_id in parent_evidence_result_ids:
            parent = await self.repository.get(parent_id, tenant_id)
            if parent is None or parent.session_id != session_id:
                raise InvalidProvenanceReferenceError(
                    f"parent_evidence_result_id={parent_id!s} is not a "
                    f"session_id={session_id!s} evidence result in this tenant"
                )

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
        parent_evidence_result_ids: tuple[UUID, ...] = (),
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EvidenceResult:
        """Creates a NEW evidence result that supersedes an existing one
        (EVD-3.10.3) -- never mutates the original row's content.

        Raises InvalidSupersessionError (WF-HV-009 Finding A) if
        evidence_result_id is not currently the effective row for THIS
        (tenant_id, session_id, evidence_type) -- e.g. it belongs to a
        different session or evidence_type, was already superseded, or
        never existed. Without this check a caller could deactivate an
        unrelated session's effective evidence purely by supplying its
        ID, corrupting that other session's evidence set as seen by the
        Decision Engine.

        `parent_evidence_result_ids` (DP-009 §6/§7.2): unlike
        `source_reference`, a superseding row's own lineage is NOT
        reconstructable by walking `supersedes_id` back to the original
        `create()`-produced row -- a derived stage's parent set can
        itself change between attempts (DOCUMENT_FIELD_EXTRACTION's own
        freshness principle, DP-008 §4, is exactly this case), so each
        supersession must be able to record its OWN current parent set,
        not silently inherit the prior attempt's. Validated the same way
        `create()`'s is -- see `_validate_provenance`, already generic
        over both call sites.

        `mark_not_effective` on the original happens BEFORE `add()` of the
        new row, not after: PostgreSQL's partial unique index
        (ix_evidence_results_one_effective_per_type) is checked
        per-statement and cannot be deferred, so inserting the new
        effective row while the old one is still marked effective would
        violate the constraint immediately, even mid-transaction -- the
        exact ordering lesson already proven by PolicyService.mark_superseded
        preceding its own ACTIVE-row insert."""
        validate_result_payload(evidence_type, result, parent_evidence_result_ids)
        await self._validate_provenance(
            tenant_id=tenant_id,
            session_id=session_id,
            source_reference=None,
            parent_evidence_result_ids=parent_evidence_result_ids,
        )

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
            parent_evidence_result_ids=parent_evidence_result_ids,
            supersedes_id=evidence_result_id,
            produced_at=now,
            persisted_at=now,
            integrity_reference=_compute_integrity_reference(
                evidence_type=evidence_type,
                status=status,
                result=result,
                producer=producer,
                producer_version=producer_version,
                score=score,
                quality=quality,
            ),
        )
        superseded = await self.repository.mark_not_effective(
            evidence_result_id, tenant_id, session_id, evidence_type
        )
        if not superseded:
            raise InvalidSupersessionError(
                f"evidence_result_id={evidence_result_id!s} is not the current "
                f"effective {evidence_type.value} result for session_id="
                f"{session_id!s} in this tenant -- it does not exist, belongs "
                "to a different session/evidence_type, or was already superseded"
            )
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

    async def list_effective_for_session(
        self, *, session_id: UUID, tenant_id: str
    ) -> Sequence[EvidenceResult]:
        """DE-003 §11's input: supersession-filtered, at most one row per
        evidence_type (the database's own partial unique index is the
        primary guarantee; core.evidence_result.effective's defensive
        resolver is the fallback -- neither lives here). The evaluation
        orchestration boundary (core.decision.orchestration) is this
        method's only caller today."""
        return await self.repository.list_effective_for_session(session_id, tenant_id)

    async def get_effective_for_session_by_type(
        self, *, session_id: UUID, tenant_id: str, evidence_type: EvidenceResultType
    ) -> EvidenceResult | None:
        """At most one row is possible here when the partial unique index
        holds (DE-003 §11) -- a thin, type-scoped convenience over
        list_effective_for_session() for callers (e.g.
        core.document.processor's DocumentProcessor) that need to check a
        single stage's existing effective result before deciding whether
        to create() or supersede() (DP-001 Decision 4's per-stage
        convergence rule)."""
        results = await self.repository.list_effective_for_session_by_type(
            session_id, tenant_id, evidence_type
        )
        return results[0] if results else None

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
