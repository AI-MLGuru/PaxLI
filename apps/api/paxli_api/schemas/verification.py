from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.audit.enums import AuditActorType, AuditEventType, AuditStatus
from core.decision.enums import DecisionOutcome
from core.deletion.enums import DeletionBasis
from core.deletion.validation import MAX_BASIS_REFERENCE_LENGTH
from core.evidence.enums import EvidenceSource, EvidenceType
from core.verification.enums import AssuranceLevel, VerificationStatus


class CreateVerificationSessionRequest(BaseModel):
    external_reference: str | None = Field(default=None, max_length=256)
    assurance_level: AssuranceLevel = AssuranceLevel.STANDARD


class PolicyReferenceResponse(BaseModel):
    id: str
    version: int
    hash: str


class DecisionProjection(BaseModel):
    outcome: DecisionOutcome
    reason_codes: tuple[str, ...]
    policy: PolicyReferenceResponse


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
    # WF-001 §9: read-time DecisionResult projection, never a
    # denormalized column on verification_sessions -- populated if and
    # only if status == COMPLETED, None for every other status, never a
    # partial or speculative decision.
    decision: DecisionProjection | None = None


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
    model_config = ConfigDict(from_attributes=True)

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


class DeleteEvidenceRequest(BaseModel):
    deletion_basis: DeletionBasis
    basis_reference: str | None = Field(default=None, max_length=MAX_BASIS_REFERENCE_LENGTH)


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    tenant_id: str
    session_id: UUID | None
    event_type: AuditEventType
    actor_type: AuditActorType
    actor_id: str | None
    occurred_at: datetime
    request_id: str | None
    correlation_id: str | None
    component: str
    action: str
    status: AuditStatus
    reason_code: str | None
    metadata: dict[str, object]


class AuditEventListEnvelope(BaseModel):
    data: list[AuditEventResponse]
    meta: ResponseMeta
