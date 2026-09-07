from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from core.evidence.enums import EvidenceSource, EvidenceType


class Evidence(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    tenant_id: str
    evidence_type: EvidenceType
    source: EvidenceSource
    object_key: str
    checksum: str
    mime_type: str
    size_bytes: int = Field(gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    retention_until: datetime | None = None
