from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from core.evidence.models import Evidence


class EvidenceRepository(Protocol):
    async def add(self, evidence: Evidence, idempotency_key: str | None = None) -> Evidence: ...

    async def get_by_idempotency_key(
        self, tenant_id: str, session_id: UUID, idempotency_key: str
    ) -> Evidence | None: ...

    async def list_for_session(self, session_id: UUID, tenant_id: str) -> Sequence[Evidence]: ...
