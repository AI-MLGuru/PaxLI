from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from core.policy.condition import Condition
from core.policy.enums import PolicyStatus
from core.verification.enums import AssuranceLevel

SCHEMA_VERSION = "1.0"


class VerificationPolicy(BaseModel):
    """Part V §5.8-5.12 policy definition + Invariant 07 immutable version.

    `id` identifies this specific immutable version; `policy_id` is the
    stable, caller-supplied identity that persists across versions
    (DEC-5.8.2). `canonical_hash` is always server-computed from the
    normalized content (Foundation-009 discovery question 9) -- never
    caller-supplied, same discipline as EvidenceResult.integrity_reference.

    `gates`, `rules`, `thresholds`, `conflict_resolution` are validated,
    schema-versioned but otherwise loosely-typed envelopes (Foundation-009
    discovery decision #4): this foundation proves they are well-formed,
    inert data, never that they produce a correct decision. Only
    `conditions` (DEC-5.13-5.17) gets full structural rigor here, because
    Foundation-008's evidence-result schemas make that rigor possible today.

    Constitutional rule, enforced structurally: this model has no field
    that represents a verification outcome, and nothing in core.policy
    evaluates `conditions`/`gates`/`rules` against evidence. Storing a
    policy establishes "this is the authoritative, immutable policy that
    exists" -- not "given this evidence, this is the decision."
    """

    id: UUID = Field(default_factory=uuid4)
    policy_id: str
    version: int
    tenant_id: str
    assurance_level: AssuranceLevel
    schema_version: str = SCHEMA_VERSION
    status: PolicyStatus = PolicyStatus.ACTIVE
    evidence_requirements: dict[str, Any] = Field(default_factory=dict)
    conditions: Condition | None = None
    gates: tuple[dict[str, Any], ...] = ()
    rules: tuple[dict[str, Any], ...] = ()
    thresholds: dict[str, float] = Field(default_factory=dict)
    conflict_resolution: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    canonical_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    activated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    superseded_at: datetime | None = None
    supersedes_id: UUID | None = None
    created_by: str
