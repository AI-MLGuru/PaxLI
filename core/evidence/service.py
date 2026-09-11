from collections.abc import Sequence
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from core.audit.enums import AuditActorType, AuditDurability, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.deletion.enums import DeletionBasis
from core.deletion.validation import validate_deletion_request
from core.evidence.enums import EvidenceSource, EvidenceType
from core.evidence.media_validation import verify_evidence_media
from core.evidence.models import Evidence, EvidenceTombstone
from core.evidence.repository import EvidenceRepository
from core.verification.service import SessionExpiredError, VerificationSessionService

if TYPE_CHECKING:
    from infrastructure.storage.interface import ObjectStorage

_SYSTEM_COMPONENT = "evidence"


class EvidenceNotFoundError(Exception):
    """Raised by write-path operations (deletion) that cannot proceed
    without an existing, tenant-scoped evidence row -- unlike list()/get(),
    which return an empty/None result, a deletion request against evidence
    that was never created (or belongs to another tenant) is a genuine
    error, not a no-op (EVD-3.26.2)."""


class EvidenceDeletedError(Exception):
    """Raised by the read path when a tenant-scoped tombstone exists for
    the requested evidence_id -- Invariant-06 remediation Phase 4's firm
    choice: a deleted evidence ID must remain distinguishable from one that
    never existed (410 Gone), never collapsed into an ordinary 404. Raised
    regardless of whether the tombstone has executed_at set: once deletion
    has been durably requested, the resource must stop being served as
    live even if reconciliation hasn't physically caught up yet."""


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
        if session.status.value in {"EXPIRED", "CANCELLED"}:
            raise SessionExpiredError
        if idempotency_key:
            existing = await self.repository.get_by_idempotency_key(
                tenant_id, session_id, idempotency_key
            )
            if existing is not None:
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
        )
        try:
            return await self.repository.add(evidence, idempotency_key)
        except Exception:
            await self.storage.delete(object_key)
            raise

    async def list(self, *, session_id: UUID, tenant_id: str) -> Sequence[Evidence]:
        await self.session_service.get(session_id=session_id, tenant_id=tenant_id)
        return await self.repository.list_for_session(session_id, tenant_id)

    async def get(self, *, evidence_id: UUID, tenant_id: str) -> Evidence | None:
        return await self.repository.get(evidence_id, tenant_id)

    async def get_tombstone(
        self, *, evidence_id: UUID, tenant_id: str
    ) -> EvidenceTombstone | None:
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
            raise EvidenceNotFoundError(
                f"no evidence_id={evidence_id!s} for this tenant to delete"
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
            raise RuntimeError(
                "EvidenceService was constructed without a deletion_reconciler"
            )
        return await self.deletion_reconciler.reconcile(
            evidence_id=evidence_id,
            tenant_id=tenant_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )
