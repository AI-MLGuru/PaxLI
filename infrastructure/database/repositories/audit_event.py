from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit.enums import AuditEventType
from core.audit.models import AuditEvent
from infrastructure.database.models.audit_event import AuditEventRecord

_MAX_LIST_FOR_TENANT_LIMIT = 500


class SqlAlchemyAuditEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, event: AuditEvent, dedupe_key: str | None = None) -> AuditEvent:
        record = AuditEventRecord.from_domain(event, dedupe_key)
        self.session.add(record)
        await self.session.flush()
        return record.to_domain()

    async def get_by_dedupe_key(
        self, tenant_id: str, session_id: UUID | None, dedupe_key: str
    ) -> AuditEvent | None:
        statement = select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == tenant_id,
            AuditEventRecord.session_id == (str(session_id) if session_id else None),
            AuditEventRecord.dedupe_key == dedupe_key,
        )
        record = (await self.session.execute(statement)).scalar_one_or_none()
        return record.to_domain() if record else None

    async def list_for_session(self, session_id: UUID, tenant_id: str) -> Sequence[AuditEvent]:
        statement = (
            select(AuditEventRecord)
            .where(
                AuditEventRecord.session_id == str(session_id),
                AuditEventRecord.tenant_id == tenant_id,
            )
            .order_by(AuditEventRecord.occurred_at, AuditEventRecord.event_id)
        )
        records = (await self.session.execute(statement)).scalars().all()
        return [record.to_domain() for record in records]

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        event_type: AuditEventType | None = None,
        actor_id: str | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[AuditEvent]:
        bounded_limit = min(max(limit, 1), _MAX_LIST_FOR_TENANT_LIMIT)
        conditions = [AuditEventRecord.tenant_id == tenant_id]
        if event_type is not None:
            conditions.append(AuditEventRecord.event_type == event_type.value)
        if actor_id is not None:
            conditions.append(AuditEventRecord.actor_id == actor_id)
        if occurred_after is not None:
            conditions.append(AuditEventRecord.occurred_at >= occurred_after)
        if occurred_before is not None:
            conditions.append(AuditEventRecord.occurred_at <= occurred_before)
        statement = (
            select(AuditEventRecord)
            .where(*conditions)
            .order_by(AuditEventRecord.occurred_at.desc(), AuditEventRecord.event_id)
            .limit(bounded_limit)
        )
        records = (await self.session.execute(statement)).scalars().all()
        return [record.to_domain() for record in records]
