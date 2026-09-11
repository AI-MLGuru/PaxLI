from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from core.deletion.enums import DeletionBasis
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


class EvidenceTombstone(BaseModel):
    """Part III §3.27's `EvidenceDeleted` object, literally. Metadata-only
    by construction -- there is no field on this model capable of holding
    raw biometric/document content (PRV-11.30.1).

    `executed_at` is the authoritative indication that the defined v1
    deletion scope (object storage + database content) has actually been
    satisfied -- not merely that deletion was requested or attempted
    (Invariant-06 remediation review). A tombstone with `requested_at` set
    and `executed_at` still None is a truthful, safely-retryable incomplete
    state, never reported as a completed deletion.

    `evidence_integrity_reference` reuses the same value as the original
    Evidence.checksum -- the spec's own field name for what this codebase
    already calls the integrity reference.
    """

    evidence_id: UUID
    session_id: UUID
    tenant_id: str
    deletion_basis: DeletionBasis
    basis_reference: str | None = None
    authorized_by: str
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    executed_at: datetime | None = None
    evidence_integrity_reference: str
