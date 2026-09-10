from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType

SCHEMA_VERSION = "1.0"


class ModelReference(BaseModel):
    model_id: str
    model_version: str
    runtime: str | None = None
    runtime_version: str | None = None
    configuration_reference: str | None = None


class EvidenceResult(BaseModel):
    """Part III's normative evidence object (EVD-3.34).

    Distinct from core.evidence.models.Evidence (Foundation-003's Capture
    concept -- a raw selfie/document/liveness upload): this represents a
    processing component's *interpreted result*, e.g. a face-match score.
    The two are linked only through the optional `source_reference`; the
    capture model is not modified or extended by this one.

    Constitutional rule, enforced structurally, not just documented: this
    model carries no policy reference and no verification-decision field.
    An EvidenceResult may exist without a successful verification decision;
    a verification decision must never be represented as an EvidenceResult.

    `integrity_reference`, `id`, `persisted_at` are server-computed by
    EvidenceResultService, never caller-supplied (EVD-3.9.5: integrity
    checks must not rely exclusively on client-provided values).
    """

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    session_id: UUID
    evidence_type: EvidenceResultType
    schema_version: str = SCHEMA_VERSION
    status: EvidenceResultStatus
    result: dict[str, Any] | None = None
    reason_codes: tuple[str, ...] = ()
    score: float | None = None
    quality: float | None = None
    producer: str
    producer_version: str
    model_reference: ModelReference | None = None
    source_reference: UUID | None = None
    parent_evidence_result_ids: tuple[UUID, ...] = ()
    supersedes_id: UUID | None = None
    produced_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    persisted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    integrity_reference: str
    retention_until: datetime | None = None
