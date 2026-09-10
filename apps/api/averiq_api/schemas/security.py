from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.api.averiq_api.schemas.verification import ResponseMeta
from core.security.models import CredentialScope


class IssueCredentialRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scope: CredentialScope = CredentialScope.OPERATIONAL
    expires_in_days: int | None = Field(default=None, gt=0, le=3650)


class RotateCredentialRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    expires_in_days: int | None = Field(default=None, gt=0, le=3650)


class IssuedCredentialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    credential_id: UUID
    tenant_id: str
    name: str
    scope: CredentialScope
    secret: str
    expires_at: datetime | None


class IssuedCredentialEnvelope(BaseModel):
    data: IssuedCredentialResponse
    meta: ResponseMeta
