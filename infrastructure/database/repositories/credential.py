from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.security.models import CredentialRecord
from infrastructure.database.models.credential import CredentialRecordModel


class SqlAlchemyCredentialStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, credential: CredentialRecord) -> CredentialRecord:
        self.session.add(CredentialRecordModel.from_domain(credential))
        await self.session.flush()
        return credential

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
