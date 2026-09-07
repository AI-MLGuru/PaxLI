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

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = {
    "authorization",
    "access_token",
    "api_key",
    "cookie",
    "document",
    "embedding",
    "image",
    "password",
    "secret",
    "token",
}
_MAX_STRING_LENGTH = 512
_MAX_METADATA_ITEMS = 50


class AuditPersistenceError(RuntimeError):
    pass


def sanitize_metadata(value: Any, *, key: str | None = None) -> Any:
    if key and any(sensitive in key.lower() for sensitive in _SENSITIVE_KEYS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_metadata(item_value, key=str(item_key))
            for item_key, item_value in list(value.items())[:_MAX_METADATA_ITEMS]
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_metadata(item) for item in list(value)[:_MAX_METADATA_ITEMS]]
    if isinstance(value, (bytes, bytearray)):
        return "[REDACTED]"
    if isinstance(value, str):
        return value[:_MAX_STRING_LENGTH]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:_MAX_STRING_LENGTH]


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
            logger.exception(
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
