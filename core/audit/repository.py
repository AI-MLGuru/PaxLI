from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from core.audit.enums import AuditEventType
from core.audit.models import AuditEvent


class AuditEventRepository(Protocol):
    async def add(self, event: AuditEvent, dedupe_key: str | None = None) -> AuditEvent: ...

    async def get_by_dedupe_key(
        self, tenant_id: str, session_id: UUID | None, dedupe_key: str
    ) -> AuditEvent | None: ...

    async def list_for_session(self, session_id: UUID, tenant_id: str) -> Sequence[AuditEvent]: ...

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
        """Governance/management retrieval -- not session-scoped, unlike
        list_for_session (Invariant-12 remediation 3: POLICY_ACTIVATED,
        CREDENTIAL_*, and other non-session-scoped governed events had no
        API retrieval path at all before this). `limit` is always bounded
        -- an unbounded query against a growing audit table is its own
        operational hazard (REL-10.16)."""
        ...
