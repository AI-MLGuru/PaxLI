from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security.models import CredentialRecord
from infrastructure.database.models.credential import CredentialRecordModel


class SqlAlchemyCredentialStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(
        self, credential: CredentialRecord, idempotency_key: str | None = None
    ) -> CredentialRecord:
        self.session.add(CredentialRecordModel.from_domain(credential, idempotency_key))
        await self.session.flush()
        return credential

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> CredentialRecord | None:
        statement = select(CredentialRecordModel).where(
            CredentialRecordModel.tenant_id == tenant_id,
            CredentialRecordModel.idempotency_key == idempotency_key,
        )
        record = (await self.session.execute(statement)).scalar_one_or_none()
        return record.to_domain() if record is not None else None

    async def get(self, credential_id: UUID, tenant_id: str) -> CredentialRecord | None:
        record = await self.session.get(CredentialRecordModel, str(credential_id))
        if record is None or record.tenant_id != tenant_id:
            return None
        return record.to_domain()

    async def get_by_id(self, credential_id: UUID) -> CredentialRecord | None:
        record = await self.session.get(CredentialRecordModel, str(credential_id))
        return record.to_domain() if record else None

    async def update(self, credential: CredentialRecord) -> CredentialRecord:
        record = await self.session.get(CredentialRecordModel, str(credential.credential_id))
        if record is None or record.tenant_id != credential.tenant_id:
            raise LookupError("Credential does not exist")
        record.update_from_domain(credential)
        await self.session.flush()
        return record.to_domain()
