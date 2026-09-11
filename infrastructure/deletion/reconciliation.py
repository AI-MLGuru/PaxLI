"""Concrete implementations of the Phase-2 (reconciliation) deletion
transaction Protocols declared in core.evidence.service and
core.evidence_result.service (Invariant-06 remediation Phase 3): each opens
a genuinely new session, idempotently reconciles storage/DB content, records
the required *_DELETED audit event, sets executed_at, and commits --
independent of whatever transaction the caller's own (request-phase)
session is in. Same dependency-inversion shape as
infrastructure/audit/independent.py's SqlAlchemyIndependentAuditRecorder:
the domain layer depends only on the narrow Protocol, never on SQLAlchemy
directly.

Deliberately tolerant of partial prior attempts (the decisive Phase-3
requirement): an already-executed tombstone is returned as-is without
re-doing any work; a missing storage object or DB row is treated as already
satisfied, never as an error. executed_at is set only after the object
storage, DB content deletion, and the required audit event have all
completed within this transaction -- never merely because deletion was
attempted.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.audit.enums import AuditActorType, AuditDurability, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.deletion.exceptions import TombstoneNotFoundError
from core.evidence.models import EvidenceTombstone
from core.evidence_result.models import EvidenceResultTombstone
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import (
    SqlAlchemyEvidenceResultRepository,
)

if TYPE_CHECKING:
    from core.security.keys import KeyProvider
    from infrastructure.storage.interface import ObjectStorage

_RECONCILER_ACTOR_ID = "evidence-deletion-reconciler"


class SqlAlchemyEvidenceDeletionReconciler:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], storage: "ObjectStorage"
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage

    async def reconcile(
        self,
        *,
        evidence_id: UUID,
        tenant_id: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EvidenceTombstone:
        async with self._session_factory() as session:
            repository = SqlAlchemyEvidenceRepository(session)
            audit_service = AuditService(SqlAlchemyAuditEventRepository(session))

            tombstone = await repository.get_tombstone(evidence_id, tenant_id)
            if tombstone is None:
                raise TombstoneNotFoundError(
                    f"no tombstone for evidence_id={evidence_id!s} in this tenant -- "
                    "reconciliation requires a prior request_deletion() call"
                )
            if tombstone.executed_at is not None:
                return tombstone

            # Storage delete happens BEFORE the DB row is removed: object_key
            # is only ever known while the evidence row still exists, so
            # reading it here (and deleting from storage first) is what
            # makes a missing row on a later retry safely interpretable as
            # "storage was already reconciled" rather than "we lost track
            # of what to delete".
            evidence = await repository.get(evidence_id, tenant_id)
            if evidence is not None:
                await self._storage.delete(evidence.object_key)
            await repository.delete_content(evidence_id, tenant_id)

            await audit_service.record(
                tenant_id=tenant_id,
                session_id=tombstone.session_id,
                event_type=AuditEventType.EVIDENCE_DELETED,
                component="evidence",
                action="reconcile_deletion",
                status=AuditStatus.SUCCESS,
                actor_type=AuditActorType.SYSTEM,
                actor_id=_RECONCILER_ACTOR_ID,
                request_id=request_id,
                correlation_id=correlation_id,
                metadata={
                    "evidence_id": str(evidence_id),
                    "deletion_basis": tombstone.deletion_basis.value,
                },
                dedupe_key=f"evidence-deleted:{evidence_id}",
                durability=AuditDurability.REQUIRED,
            )

            updated = await repository.mark_tombstone_executed(
                evidence_id, tenant_id, datetime.now(UTC)
            )
            await session.commit()
            return updated


class SqlAlchemyEvidenceResultDeletionReconciler:
    """No object-storage step: an EvidenceResult's sensitive payload lives
    inline in the evidence_results row (plaintext JSON or ciphertext),
    never in object storage, so reconciliation here is DB-content-delete +
    audit + executed_at only."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        key_provider: "KeyProvider",
        key_id: str,
    ) -> None:
        self._session_factory = session_factory
        self._key_provider = key_provider
        self._key_id = key_id

    async def reconcile(
        self,
        *,
        evidence_result_id: UUID,
        tenant_id: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EvidenceResultTombstone:
        async with self._session_factory() as session:
            repository = SqlAlchemyEvidenceResultRepository(
                session, self._key_provider, self._key_id
            )
            audit_service = AuditService(SqlAlchemyAuditEventRepository(session))

            tombstone = await repository.get_tombstone(evidence_result_id, tenant_id)
            if tombstone is None:
                raise TombstoneNotFoundError(
                    f"no tombstone for evidence_result_id={evidence_result_id!s} in this "
                    "tenant -- reconciliation requires a prior request_deletion() call"
                )
            if tombstone.executed_at is not None:
                return tombstone

            await repository.delete_content(evidence_result_id, tenant_id)

            await audit_service.record(
                tenant_id=tenant_id,
                session_id=tombstone.session_id,
                event_type=AuditEventType.EVIDENCE_RESULT_DELETED,
                component="evidence_result",
                action="reconcile_deletion",
                status=AuditStatus.SUCCESS,
                actor_type=AuditActorType.SYSTEM,
                actor_id=_RECONCILER_ACTOR_ID,
                request_id=request_id,
                correlation_id=correlation_id,
                metadata={
                    "evidence_result_id": str(evidence_result_id),
                    "deletion_basis": tombstone.deletion_basis.value,
                },
                dedupe_key=f"evidence-result-deleted:{evidence_result_id}",
                durability=AuditDurability.REQUIRED,
            )

            updated = await repository.mark_tombstone_executed(
                evidence_result_id, tenant_id, datetime.now(UTC)
            )
            await session.commit()
            return updated
