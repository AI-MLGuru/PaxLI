import hashlib
import json
from collections.abc import Sequence
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from core.audit.enums import AuditActorType, AuditDurability, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.deletion.enums import DeletionBasis
from core.deletion.exceptions import DeletionBlockedByDependentsError
from core.deletion.validation import validate_deletion_request
from core.evidence.enums import EvidenceSource, EvidenceType
from core.evidence.exceptions import (
    EvidenceDeletedError,
    EvidenceNotFoundError,
    IdempotencyKeyConflictError,
    IdempotencyKeyReusedError,
)
from core.evidence.media_validation import verify_evidence_media
from core.evidence.models import Evidence, EvidenceTombstone
from core.evidence.repository import EvidenceRepository
from core.verification.enums import EVIDENCE_SUBMISSION_ALLOWED_STATUSES
from core.verification.service import SessionExpiredError, VerificationSessionService

if TYPE_CHECKING:
    from infrastructure.storage.interface import ObjectStorage

__all__ = [
    "EvidenceDeletedError",
    "EvidenceDeletionReconciler",
    "EvidenceNotFoundError",
    "EvidenceService",
    "IdempotencyKeyConflictError",
    "IdempotencyKeyReusedError",
]

_SYSTEM_COMPONENT = "evidence"


def _compute_evidence_submission_fingerprint(
    *,
    tenant_id: str,
    session_id: UUID,
    evidence_type: EvidenceType,
    checksum: str,
) -> str:
    """WF-001 §10: the canonical fingerprint of an evidence submission
    request -- same canonical-JSON/SHA-256 technique as
    core.policy.canonicalization and evidence_result.service's
    _compute_integrity_reference, applied to the four fields that define
    "what was being submitted." `checksum` is the server-computed hash of
    the actual uploaded bytes (never client-supplied), so two requests
    with the same idempotency key but different file content always
    fingerprint differently, even if every other field matches."""
    canonical = json.dumps(
        {
            "tenant_id": tenant_id,
            "session_id": str(session_id),
            "evidence_type": evidence_type.value,
            "checksum": checksum,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reject_if_fingerprint_mismatch(
    *,
    existing_fingerprint: str | None,
    expected_fingerprint: str,
    idempotency_key: str,
    session_id: UUID,
) -> None:
    """WF-001 §10 / WF-4.9.3: the one comparison both the upfront
    idempotency check and the concurrent-insert recovery path must apply
    identically -- convergence (fingerprints match) or rejection
    (IdempotencyKeyReusedError) must never depend on which of two racing
    requests happened to observe the existing row first."""
    if existing_fingerprint != expected_fingerprint:
        raise IdempotencyKeyReusedError(
            f"idempotency_key={idempotency_key!r} was already used for a "
            f"materially different evidence submission in session_id={session_id!s}"
        )


class EvidenceDeletionReconciler(Protocol):
    """Performs the Phase-2 (reconciliation) deletion transaction in a
    session independent of the caller's own unit of work: storage delete,
    DB content delete, the required EVIDENCE_DELETED audit event, and
    executed_at, all committed together (Invariant-06 remediation Phase
    3). Same dependency-inversion shape as
    core.policy.service.IndependentAuditRecorder: core/ stays
    infrastructure-agnostic, the real implementation
    (infrastructure/deletion/reconciliation.py) owns its own session
    lifecycle."""

    async def reconcile(
        self,
        *,
        evidence_id: UUID,
        tenant_id: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EvidenceTombstone: ...


class EvidenceService:
    def __init__(
        self,
        repository: EvidenceRepository,
        session_service: VerificationSessionService,
        storage: "ObjectStorage",
        audit_service: AuditService,
        deletion_reconciler: EvidenceDeletionReconciler | None = None,
        retention_days: int = 30,
    ) -> None:
        self.repository = repository
        self.session_service = session_service
        self.storage = storage
        self.audit_service = audit_service
        self.deletion_reconciler = deletion_reconciler
        self.retention_days = retention_days

    async def add(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        evidence_type: EvidenceType,
        content: bytes,
        checksum: str,
        metadata: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> Evidence:
        session = await self.session_service.get(session_id=session_id, tenant_id=tenant_id)
        # WF-4.19.2 / WF-001 §8: rejected before ANY mutation -- no media
        # verification, no object storage write, no EvidenceRecord insert.
        # An allow-list, not a deny-list of terminal states: SUBMITTED and
        # PROCESSING must also reject ordinary submission despite neither
        # being terminal (the client already signaled "done" by calling
        # /submit), so "not terminal" is not the same test as "still
        # collecting evidence." An allow-list also fails safe automatically
        # against any future new status, rather than requiring a deny-list
        # to be remembered and extended.
        if session.status not in EVIDENCE_SUBMISSION_ALLOWED_STATUSES:
            raise SessionExpiredError

        fingerprint = _compute_evidence_submission_fingerprint(
            tenant_id=tenant_id,
            session_id=session_id,
            evidence_type=evidence_type,
            checksum=checksum,
        )
        if idempotency_key:
            existing = await self.repository.get_by_idempotency_key(
                tenant_id, session_id, idempotency_key
            )
            if existing is not None:
                _reject_if_fingerprint_mismatch(
                    existing_fingerprint=existing.fingerprint,
                    expected_fingerprint=fingerprint,
                    idempotency_key=idempotency_key,
                    session_id=session_id,
                )
                return existing

        # The client-supplied mime_type is never trusted for storage/response
        # purposes (SEC-7.22.2); the actual bytes establish the media type.
        verified_mime_type = verify_evidence_media(content)
        object_key = f"{tenant_id}/{session_id}/{evidence_type.value.lower()}/{checksum}"
        await self.storage.put(object_key, content, verified_mime_type)
        evidence = Evidence(
            session_id=session_id,
            tenant_id=tenant_id,
            evidence_type=evidence_type,
            source=EvidenceSource.CLIENT,
            object_key=object_key,
            checksum=checksum,
            mime_type=verified_mime_type,
            size_bytes=len(content),
            metadata=metadata,
            retention_until=session.created_at + timedelta(days=self.retention_days),
            fingerprint=fingerprint,
        )
        try:
            return await self.repository.add(evidence, idempotency_key)
        except IdempotencyKeyConflictError:
            await self.storage.delete(object_key)
            if idempotency_key is None:
                # Only ever raised when an idempotency_key drove the
                # unique-constraint conflict -- should be unreachable.
                # Surfacing the error rather than fabricating a result
                # keeps that assumption honest (same posture as
                # DecisionPersistenceService.persist()'s identical
                # "should be unreachable" branch).
                raise
            winner = await self.repository.get_by_idempotency_key(
                tenant_id, session_id, idempotency_key
            )
            if winner is None:
                raise
            _reject_if_fingerprint_mismatch(
                existing_fingerprint=winner.fingerprint,
                expected_fingerprint=fingerprint,
                idempotency_key=idempotency_key,
                session_id=session_id,
            )
            return winner
        except Exception:
            await self.storage.delete(object_key)
            raise

    async def list(self, *, session_id: UUID, tenant_id: str) -> Sequence[Evidence]:
        await self.session_service.get(session_id=session_id, tenant_id=tenant_id)
        return await self.repository.list_for_session(session_id, tenant_id)

    async def get(self, *, evidence_id: UUID, tenant_id: str) -> Evidence | None:
        return await self.repository.get(evidence_id, tenant_id)

    async def get_tombstone(self, *, evidence_id: UUID, tenant_id: str) -> EvidenceTombstone | None:
        return await self.repository.get_tombstone(evidence_id, tenant_id)

    async def request_deletion(
        self,
        *,
        evidence_id: UUID,
        tenant_id: str,
        deletion_basis: DeletionBasis,
        basis_reference: str | None,
        authorized_by: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EvidenceTombstone:
        """Phase-1 (request) transaction: validate, create the tombstone,
        record the REQUIRED EVIDENCE_DELETION_REQUESTED audit event, and
        return -- no storage or DB content deletion happens here (Invariant-
        06 remediation Phase 3 decision). Both writes land in the caller's
        ambient session; a required-audit failure rolls back the tombstone
        with it, so nothing is observable until the caller's single commit
        (same statement-order reasoning as PolicyService.create_and_activate).

        Naturally idempotent: replaying a request against an
        already-tombstoned evidence_id (requested or already executed)
        returns the existing tombstone unchanged, without re-emitting audit.
        A concurrent request racing for the same evidence_id instead
        surfaces DeletionAlreadyRequestedError (core.deletion.exceptions) --
        a translation of the tombstone table's primary key, never a silent
        application-level check-then-insert.
        """
        validate_deletion_request(
            deletion_basis=deletion_basis,
            basis_reference=basis_reference,
            authorized_by=authorized_by,
        )

        existing_tombstone = await self.repository.get_tombstone(evidence_id, tenant_id)
        if existing_tombstone is not None:
            return existing_tombstone

        evidence = await self.repository.get(evidence_id, tenant_id)
        if evidence is None:
            raise EvidenceNotFoundError(f"no evidence_id={evidence_id!s} for this tenant to delete")
        if await self.repository.has_dependent_evidence_results(evidence_id, tenant_id):
            raise DeletionBlockedByDependentsError(
                f"evidence_id={evidence_id!s} has a dependent EvidenceResult "
                "(source_reference) -- delete the dependent result(s) first"
            )

        tombstone = EvidenceTombstone(
            evidence_id=evidence_id,
            session_id=evidence.session_id,
            tenant_id=tenant_id,
            deletion_basis=deletion_basis,
            basis_reference=basis_reference,
            authorized_by=authorized_by,
            evidence_integrity_reference=evidence.checksum,
        )
        saved = await self.repository.add_tombstone(tombstone)
        await self.audit_service.record(
            tenant_id=tenant_id,
            session_id=evidence.session_id,
            event_type=AuditEventType.EVIDENCE_DELETION_REQUESTED,
            component=_SYSTEM_COMPONENT,
            action="request_deletion",
            status=AuditStatus.SUCCESS,
            actor_type=AuditActorType.CLIENT,
            actor_id=authorized_by,
            request_id=request_id,
            correlation_id=correlation_id,
            metadata={
                "evidence_id": str(evidence_id),
                "deletion_basis": deletion_basis.value,
            },
            dedupe_key=f"evidence-deletion-requested:{evidence_id}",
            durability=AuditDurability.REQUIRED,
        )
        return saved

    async def reconcile_deletion(
        self,
        *,
        evidence_id: UUID,
        tenant_id: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EvidenceTombstone:
        """Phase-2 (reconciliation) transaction: delegates to an
        independently-committing EvidenceDeletionReconciler (Invariant-06
        remediation Phase 3) -- never the caller's own ambient session,
        since reconciliation must be able to commit on its own regardless
        of whatever the request phase's session is doing."""
        if self.deletion_reconciler is None:
            raise RuntimeError("EvidenceService was constructed without a deletion_reconciler")
        return await self.deletion_reconciler.reconcile(
            evidence_id=evidence_id,
            tenant_id=tenant_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )
