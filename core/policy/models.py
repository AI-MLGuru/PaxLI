from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from core.decision.enums import DecisionOutcome
from core.policy.condition import Condition
from core.policy.enums import PolicyStatus
from core.policy.gates import Gate
from core.policy.requirements import EvidenceRequirement
from core.policy.rules import Rule
from core.policy.thresholds import ThresholdDefinition
from core.verification.enums import AssuranceLevel

SCHEMA_VERSION = "1.0"

# DE-003 §5/§10: default_outcome must never be VERIFIED -- no optimistic
# fallback is permitted when policy evaluation reaches no explicit
# conclusion (DEC-5.23.1).
_ALLOWED_DEFAULT_OUTCOMES = frozenset(
    {DecisionOutcome.REJECTED, DecisionOutcome.REVIEW_REQUIRED, DecisionOutcome.INCONCLUSIVE}
)


class VerificationPolicy(BaseModel):
    """Part V §5.8-5.12 policy definition + Invariant 07 immutable version.

    `id` identifies this specific immutable version; `policy_id` is the
    stable, caller-supplied identity that persists across versions
    (DEC-5.8.2). `canonical_hash` is always server-computed from the
    normalized content -- never caller-supplied, same discipline as
    EvidenceResult.integrity_reference.

    DE-003 formalizes what Foundation-009 deliberately left as opaque
    envelopes: `evidence_requirements`, `gates`, `rules`, and `thresholds`
    are now typed, structurally-validated collections (core.policy.gates,
    .rules, .requirements, .thresholds) instead of raw dicts. There is no
    `conflict_resolution` field -- DE-002/DE-003 §7/§9 fold conflict
    handling into `gates` (GateKind.CONFLICT) rather than maintaining a
    second, competing policy language.

    Constitutional rule, enforced structurally: this model has no field
    that represents a verification outcome beyond `default_outcome`'s
    narrow fallback role, and nothing in core.policy evaluates
    `conditions`/`gates`/`rules` against evidence. Storing a policy
    establishes "this is the authoritative, immutable policy that exists"
    -- not "given this evidence, this is the decision."
    """

    id: UUID = Field(default_factory=uuid4)
    policy_id: str
    version: int
    tenant_id: str
    assurance_level: AssuranceLevel
    schema_version: str = SCHEMA_VERSION
    status: PolicyStatus = PolicyStatus.ACTIVE
    evidence_requirements: tuple[EvidenceRequirement, ...] = ()
    conditions: Condition | None = None
    gates: tuple[Gate, ...] = ()
    rules: tuple[Rule, ...] = ()
    thresholds: tuple[ThresholdDefinition, ...] = ()
    default_outcome: DecisionOutcome | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    canonical_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    activated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    superseded_at: datetime | None = None
    supersedes_id: UUID | None = None
    created_by: str

    @model_validator(mode="after")
    def _default_outcome_is_never_verified(self) -> "VerificationPolicy":
        if (
            self.default_outcome is not None
            and self.default_outcome not in _ALLOWED_DEFAULT_OUTCOMES
        ):
            raise ValueError(
                f"default_outcome {self.default_outcome.value!r} is not permitted -- "
                f"must be one of {sorted(o.value for o in _ALLOWED_DEFAULT_OUTCOMES)}"
            )
        return self
