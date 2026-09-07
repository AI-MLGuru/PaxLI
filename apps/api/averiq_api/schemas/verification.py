from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.evidence.enums import EvidenceSource, EvidenceType
from core.verification.enums import AssuranceLevel, VerificationStatus


class CreateVerificationSessionRequest(BaseModel):
    external_reference: str | None = Field(default=None, max_length=256)
    assurance_level: AssuranceLevel = AssuranceLevel.STANDARD


class VerificationSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str
    external_reference: str | None
    status: VerificationStatus
    assurance_level: AssuranceLevel
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None


class ResponseMeta(BaseModel):
    request_id: str


class SessionEnvelope(BaseModel):
    data: VerificationSessionResponse
    meta: ResponseMeta


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody
    meta: ResponseMeta


class EvidenceResponse(BaseModel):
    id: UUID
    session_id: UUID
    evidence_type: EvidenceType
    source: EvidenceSource
    checksum: str
    mime_type: str
    size_bytes: int
    metadata: dict[str, object]
    created_at: datetime
    retention_until: datetime | None


class EvidenceListEnvelope(BaseModel):
    data: list[EvidenceResponse]
    meta: ResponseMeta
