import logging
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from core.audit.enums import (
    AuditActorType,
    AuditDurability,
    AuditEventType,
    AuditStatus,
)
from core.audit.models import AuditEvent
from core.audit.repository import AuditEventRepository
from core.security.classification import sanitize_metadata

logger = logging.getLogger(__name__)


class AuditPersistenceError(RuntimeError):
    pass


class AuditService:
    def __init__(self, repository: AuditEventRepository) -> None:
        self.repository = repository

    async def record(
        self,
        *,
        tenant_id: str,
        event_type: AuditEventType,
        component: str,
        action: str,
        status: AuditStatus,
        session_id: UUID | None = None,
        actor_type: AuditActorType = AuditActorType.SYSTEM,
        actor_id: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        reason_code: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        durability: AuditDurability = AuditDurability.REQUIRED,
        dedupe_key: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            tenant_id=tenant_id,
            session_id=session_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
            correlation_id=correlation_id,
            component=component,
            action=action,
            status=status,
            reason_code=reason_code,
            metadata=sanitize_metadata(metadata or {}),
        )
        try:
            if dedupe_key:
                existing = await self.repository.get_by_dedupe_key(
                    tenant_id, session_id, dedupe_key
                )
                if existing is not None:
                    return existing
            return await self.repository.add(event, dedupe_key)
        except Exception as exception:
            logger.error(
                "audit_event_persistence_failed",
                extra={"event_type": event_type.value, "session_id": str(session_id)},
            )
            if durability == AuditDurability.REQUIRED:
                raise AuditPersistenceError(
                    "Required audit event could not be persisted"
                ) from exception
            return event

    async def list_for_session(self, *, session_id: UUID, tenant_id: str) -> Sequence[AuditEvent]:
        return await self.repository.list_for_session(session_id, tenant_id)
