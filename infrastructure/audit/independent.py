"""Concrete implementation of core.policy.service.IndependentAuditRecorder
(Invariant-12 remediation 2, Option 2): opens a genuinely new session,
records one required audit event, and commits -- independent of whatever
transaction the caller's own (possibly-aborted) session is in. Same
dependency-inversion shape as core.security.keys.KeyProvider and
core.rate_limit.limiter.RateLimiterProtocol: the domain layer depends only
on the narrow Protocol, never on SQLAlchemy directly.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.audit.enums import AuditActorType, AuditDurability, AuditEventType, AuditStatus
from core.audit.service import AuditService
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository


class SqlAlchemyIndependentAuditRecorder:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_independently(
        self,
        *,
        tenant_id: str,
        event_type: AuditEventType,
        component: str,
        action: str,
        actor_type: AuditActorType,
        actor_id: str | None,
        request_id: str | None,
        correlation_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        async with self._session_factory() as session:
            audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
            await audit_service.record(
                tenant_id=tenant_id,
                event_type=event_type,
                component=component,
                action=action,
                status=AuditStatus.FAILURE,
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
                correlation_id=correlation_id,
                metadata=metadata,
                durability=AuditDurability.REQUIRED,
            )
            await session.commit()
