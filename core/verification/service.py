from uuid import UUID

from core.verification.enums import AssuranceLevel, VerificationStatus
from core.verification.models import VerificationSession
from core.verification.repository import VerificationSessionRepository


class SessionNotFoundError(Exception):
    pass


class SessionExpiredError(Exception):
    pass


class VerificationSessionService:
    def __init__(
        self, repository: VerificationSessionRepository, session_ttl_minutes: int = 30
    ) -> None:
        self.repository = repository
        self.session_ttl_minutes = session_ttl_minutes

    async def create(
        self,
        *,
        tenant_id: str,
        external_reference: str | None,
        assurance_level: AssuranceLevel,
        idempotency_key: str | None = None,
    ) -> VerificationSession:
        if idempotency_key:
            existing = await self.repository.get_by_idempotency_key(tenant_id, idempotency_key)
            if existing is not None:
                return existing
        session = VerificationSession.create(
            tenant_id=tenant_id,
            external_reference=external_reference,
            assurance_level=assurance_level,
            ttl_minutes=self.session_ttl_minutes,
        )
        return await self.repository.add(session, idempotency_key)

    async def get(self, *, session_id: UUID, tenant_id: str) -> VerificationSession:
        session = await self.repository.get(session_id, tenant_id)
        if session is None:
            raise SessionNotFoundError
        if session.expire_if_needed():
            await self.repository.update(session)
        return session

    async def cancel(self, *, session_id: UUID, tenant_id: str) -> VerificationSession:
        session = await self.get(session_id=session_id, tenant_id=tenant_id)
        if session.status == VerificationStatus.EXPIRED:
            raise SessionExpiredError
        session.transition_to(VerificationStatus.CANCELLED)
        return await self.repository.update(session)
