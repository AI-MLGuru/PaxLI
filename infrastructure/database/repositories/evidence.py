from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.evidence.models import Evidence
from infrastructure.database.models.evidence import EvidenceRecord


class SqlAlchemyEvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self, evidence: Evidence, idempotency_key: str | None = None
    ) -> Evidence:
        record = EvidenceRecord.from_domain(evidence, idempotency_key)
        self.session.add(record)
        await self.session.commit()
        return record.to_domain()

    async def get_by_idempotency_key(
        self, tenant_id: str, session_id: UUID, idempotency_key: str
    ) -> Evidence | None:
        statement = select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id,
            EvidenceRecord.session_id == str(session_id),
            EvidenceRecord.idempotency_key == idempotency_key,
        )
        record = (await self.session.execute(statement)).scalar_one_or_none()
        return record.to_domain() if record else None

    async def list_for_session(
        self, session_id: UUID, tenant_id: str
    ) -> Sequence[Evidence]:
        statement = (
            select(EvidenceRecord)
            .where(
                EvidenceRecord.session_id == str(session_id),
                EvidenceRecord.tenant_id == tenant_id,
            )
            .order_by(EvidenceRecord.created_at)
        )
        records = (await self.session.execute(statement)).scalars().all()
        return [record.to_domain() for record in records]
