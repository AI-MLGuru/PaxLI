from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from core.verification.enums import AssuranceLevel, VerificationStatus


class VerificationSession(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    status: VerificationStatus = VerificationStatus.CREATED
    assurance_level: AssuranceLevel = AssuranceLevel.STANDARD
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
