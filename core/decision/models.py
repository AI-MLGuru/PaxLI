"""DE-003 §12: the decision domain.

Three shapes, one logical row:

    DecisionCandidate   what the pure evaluator produces, in memory only
    DecisionResult      the public projection of the persisted row
    DecisionProvenance  the same row's full internal projection

`DecisionCandidate` deliberately carries neither `decision_id` nor
`created_at`. Both are non-deterministic (a fresh UUID, a wall-clock read)
and DEC-5.25.1 forbids the evaluator from depending on either; assigning
them is the persistence layer's job, the same discipline that already makes
`EvidenceResult.id`/`persisted_at` server-computed rather than
caller-supplied. The practical effect is that the evaluator is a pure
function by construction rather than by review: it has nothing to call.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from core.decision.enums import DecisionOutcome, EvaluationReason
from core.decision.references import EvidenceReference, PolicyReference
from core.evidence_result.models import ModelReference

# Identifies the evaluation semantics that produced a decision (DE-003 §12).
# Bumped when the engine's own interpretation changes in a way that could
# alter an outcome for identical policy + evidence -- distinct from the
# policy version, which captures a change in authorship rather than a change
# in interpretation.
DECISION_ENGINE_VERSION = "1.0.0"


class DecisionCandidate(BaseModel):
    """The pure evaluator's complete output: everything needed to persist a
    decision and audit it, and nothing that requires I/O to produce."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID
    tenant_id: str
    outcome: DecisionOutcome
    reason_codes: tuple[str, ...]
    policy_reference: PolicyReference
    evidence_references: tuple[EvidenceReference, ...] = ()
    model_references: tuple[ModelReference, ...] = ()
    calibration_references: tuple[str, ...] = ()
    prohibited_types_present: tuple[str, ...] = ()
    evaluation_reason: EvaluationReason = EvaluationReason.NORMAL
    engine_version: str = DECISION_ENGINE_VERSION


class DecisionResult(BaseModel):
    """DE-003 §12's public projection. This -- not the session's lifecycle
    status -- is the authoritative final verification outcome; `outcome` is a
    DecisionOutcome and never a VerificationStatus, keeping the
    constitutional separation between session lifecycle state and final
    decision intact at the type level."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: UUID
    session_id: UUID
    tenant_id: str
    outcome: DecisionOutcome
    reason_codes: tuple[str, ...]
    policy_reference: PolicyReference
    created_at: datetime


class DecisionProvenance(DecisionResult):
    """The same row, fully projected (DE-002 §10: one row, two projections,
    not two tables). Everything added here answers "on what basis?" --
    DEC-5.27's provenance requirement and DEC-5.34.1's "model changes that
    can alter decision semantics MUST be identifiable in provenance"."""

    evidence_references: tuple[EvidenceReference, ...] = ()
    model_references: tuple[ModelReference, ...] = ()
    calibration_references: tuple[str, ...] = ()
    prohibited_types_present: tuple[str, ...] = ()
    evaluation_reason: EvaluationReason = EvaluationReason.NORMAL
    engine_version: str = DECISION_ENGINE_VERSION

    @classmethod
    def from_candidate(
        cls, candidate: DecisionCandidate, *, decision_id: UUID, created_at: datetime
    ) -> "DecisionProvenance":
        """The single join point between the pure evaluator's output and the
        two non-deterministic values persistence owns. Nothing else is added
        or reinterpreted in between."""
        return cls(decision_id=decision_id, created_at=created_at, **candidate.model_dump())

    def as_result(self) -> DecisionResult:
        """The public projection of this same row."""
        return DecisionResult(
            decision_id=self.decision_id,
            session_id=self.session_id,
            tenant_id=self.tenant_id,
            outcome=self.outcome,
            reason_codes=self.reason_codes,
            policy_reference=self.policy_reference,
            created_at=self.created_at,
        )
