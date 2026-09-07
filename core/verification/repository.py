from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from core.verification.models import VerificationSession


class VerificationSessionRepository(Protocol):
    async def add(
        self, session: VerificationSession, idempotency_key: str | None = None
    ) -> VerificationSession: ...

    async def get(
        self, session_id: UUID, tenant_id: str
    ) -> VerificationSession | None: ...

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> VerificationSession | None: ...

    async def list(self, tenant_id: str) -> Sequence[VerificationSession]: ...

    async def update(self, session: VerificationSession) -> VerificationSession: ...
