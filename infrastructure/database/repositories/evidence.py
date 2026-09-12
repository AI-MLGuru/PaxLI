from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.deletion.exceptions import DeletionAlreadyRequestedError, TombstoneNotFoundError
from core.evidence.exceptions import IdempotencyKeyConflictError
from core.evidence.models import Evidence, EvidenceTombstone
from infrastructure.database.models.evidence import EvidenceRecord
from infrastructure.database.models.evidence_result import EvidenceResultRecord
from infrastructure.database.models.evidence_tombstone import EvidenceTombstoneRecord


class SqlAlchemyEvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, evidence: Evidence, idempotency_key: str | None = None) -> Evidence:
        """WF-001 §10: a SAVEPOINT around the insert (session.begin_nested()),
        same technique as SqlAlchemyDecisionRepository.add() -- confines a
        UNIQUE(tenant_id, session_id, idempotency_key) violation's rollback
        to exactly this insert, leaving the rest of the caller's
        request-scoped transaction (and the recovery fetch EvidenceService.
        add() performs next) unaffected."""
        record = EvidenceRecord.from_domain(evidence, idempotency_key)
        try:
            async with self.session.begin_nested():
                self.session.add(record)
                await self.session.flush()
        except IntegrityError as exception:
            raise IdempotencyKeyConflictError(
                f"tenant={evidence.tenant_id!r} session_id={evidence.session_id!s} "
                f"idempotency_key={idempotency_key!r} was already claimed by a "
                "concurrent insert"
            ) from exception
        return record.to_domain()

    async def get_by_idempotency_key(
        self, tenant_id: str, session_id: UUID, idempotency_key: str
    ) -> Evidence | None:
        statement = select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id,
            EvidenceRecord.session_id == str(session_id),
            EvidenceRecord.idempotency_key == idempotency_key,
        )
        record = (await self.session.execute(statement)).scalar_one_or_none()
        return record.to_domain() if record else None

    async def get(self, evidence_id: UUID, tenant_id: str) -> Evidence | None:
        record = await self.session.get(EvidenceRecord, str(evidence_id))
        if record is None or record.tenant_id != tenant_id:
            return None
        return record.to_domain()

    async def list_for_session(self, session_id: UUID, tenant_id: str) -> Sequence[Evidence]:
        # Excludes evidence with any tombstone (requested or executed): once
        # deletion has been durably requested, the resource must stop
        # appearing as live through every read path, not just the
        # single-item GET (Invariant-06 remediation Phase 4 consistency --
        # the row can still physically exist here for a short window before
        # reconciliation executes, or indefinitely if reconciliation is
        # retrying after a failure).
        already_tombstoned = select(EvidenceTombstoneRecord.evidence_id).where(
            EvidenceTombstoneRecord.evidence_id == EvidenceRecord.id
        )
        statement = (
            select(EvidenceRecord)
            .where(
                EvidenceRecord.session_id == str(session_id),
                EvidenceRecord.tenant_id == tenant_id,
                ~already_tombstoned.exists(),
            )
            .order_by(EvidenceRecord.created_at)
        )
        records = (await self.session.execute(statement)).scalars().all()
        return [record.to_domain() for record in records]

    async def list_expired(self, tenant_id: str, as_of: datetime) -> Sequence[Evidence]:
        already_tombstoned = select(EvidenceTombstoneRecord.evidence_id).where(
            EvidenceTombstoneRecord.evidence_id == EvidenceRecord.id
        )
        statement = (
            select(EvidenceRecord)
            .where(
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.retention_until.is_not(None),
                EvidenceRecord.retention_until <= as_of,
                ~already_tombstoned.exists(),
            )
            .order_by(EvidenceRecord.retention_until)
        )
        records = (await self.session.execute(statement)).scalars().all()
        return [record.to_domain() for record in records]

    async def has_dependent_evidence_results(self, evidence_id: UUID, tenant_id: str) -> bool:
        statement = (
            select(EvidenceResultRecord.id)
            .where(
                EvidenceResultRecord.source_reference == str(evidence_id),
                EvidenceResultRecord.tenant_id == tenant_id,
            )
            .limit(1)
        )
        return (await self.session.execute(statement)).scalar_one_or_none() is not None

    async def delete_content(self, evidence_id: UUID, tenant_id: str) -> bool:
        statement = delete(EvidenceRecord).where(
            EvidenceRecord.id == str(evidence_id),
            EvidenceRecord.tenant_id == tenant_id,
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return bool(result.rowcount)

    async def add_tombstone(self, tombstone: EvidenceTombstone) -> EvidenceTombstone:
        record = EvidenceTombstoneRecord.from_domain(tombstone)
        self.session.add(record)
        try:
            await self.session.flush()
        except IntegrityError as exception:
            raise DeletionAlreadyRequestedError(
                f"a tombstone already exists for evidence_id={tombstone.evidence_id!s}"
            ) from exception
        return record.to_domain()

    async def get_tombstone(self, evidence_id: UUID, tenant_id: str) -> EvidenceTombstone | None:
        record = await self.session.get(EvidenceTombstoneRecord, str(evidence_id))
        if record is None or record.tenant_id != tenant_id:
            return None
        return record.to_domain()

    async def mark_tombstone_executed(
        self, evidence_id: UUID, tenant_id: str, executed_at: datetime
    ) -> EvidenceTombstone:
        record = await self.session.get(EvidenceTombstoneRecord, str(evidence_id))
        if record is None or record.tenant_id != tenant_id:
            raise TombstoneNotFoundError(
                f"no tombstone for evidence_id={evidence_id!s} in this tenant"
            )
        record.executed_at = executed_at
        await self.session.flush()
        return record.to_domain()
