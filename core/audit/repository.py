from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from core.audit.models import AuditEvent


class AuditEventRepository(Protocol):
    async def add(
        self, event: AuditEvent, dedupe_key: str | None = None
    ) -> AuditEvent: ...

    async def get_by_dedupe_key(
        self, tenant_id: str, session_id: UUID | None, dedupe_key: str
    ) -> AuditEvent | None: ...

    async def list_for_session(
        self, session_id: UUID, tenant_id: str
    ) -> Sequence[AuditEvent]: ...
