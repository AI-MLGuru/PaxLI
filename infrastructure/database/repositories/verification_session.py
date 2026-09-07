from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.verification.models import VerificationSession
from infrastructure.database.models.verification_session import VerificationSessionRecord


class SqlAlchemyVerificationSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self, session: VerificationSession, idempotency_key: str | None = None
    ) -> VerificationSession:
        record = VerificationSessionRecord.from_domain(session, idempotency_key)
        self.session.add(record)
        await self.session.commit()
        return record.to_domain()

    async def get(self, session_id: UUID, tenant_id: str) -> VerificationSession | None:
        statement = select(VerificationSessionRecord).where(
            VerificationSessionRecord.id == str(session_id),
            VerificationSessionRecord.tenant_id == tenant_id,
        )
        record = (await self.session.execute(statement)).scalar_one_or_none()
        return record.to_domain() if record else None

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> VerificationSession | None:
        statement = select(VerificationSessionRecord).where(
            VerificationSessionRecord.tenant_id == tenant_id,
            VerificationSessionRecord.idempotency_key == idempotency_key,
        )
        record = (await self.session.execute(statement)).scalar_one_or_none()
        return record.to_domain() if record else None

    async def list(self, tenant_id: str) -> Sequence[VerificationSession]:
        statement = select(VerificationSessionRecord).where(
            VerificationSessionRecord.tenant_id == tenant_id
        )
        records = (await self.session.execute(statement)).scalars().all()
        return [record.to_domain() for record in records]

    async def update(self, session: VerificationSession) -> VerificationSession:
        record = await self.session.get(VerificationSessionRecord, str(session.id))
        if record is None or record.tenant_id != session.tenant_id:
            raise LookupError("Verification session does not exist")
        record.update_from_domain(session)
        await self.session.commit()
        return record.to_domain()
