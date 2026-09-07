from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from core.audit.enums import AuditActorType, AuditEventType, AuditStatus


class AuditEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    session_id: UUID | None = None
    event_type: AuditEventType
    actor_type: AuditActorType
    actor_id: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request_id: str | None = None
    correlation_id: str | None = None
    component: str
    action: str
    status: AuditStatus
    reason_code: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
