"""DE-002 §9 / DE-003 §11: the evaluator's input boundary.

`DecisionEvaluationContext` is the pure function boundary. The evaluator
fetches nothing: the policy arrives already resolved (the version pinned to
the session under early binding) and the evidence arrives already
supersession-filtered. This is what makes DEC-5.25's determinism
requirements -- no wall-clock dependence, no nondeterministic iteration
order, no uncontrolled external calls -- checkable by construction rather
than by discipline, and it is why the evaluator needs no authorization
context of its own: whatever assembles this context owns that.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.decision.enums import EvaluationReason
from core.evidence_result.effective import resolve_one_effective_per_type
from core.evidence_result.models import EvidenceResult
from core.policy.models import VerificationPolicy
from core.policy.requirements import EvidenceRequirementLevel


class DecisionEvaluationContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID
    tenant_id: str
    policy: VerificationPolicy
    effective_evidence: tuple[EvidenceResult, ...] = ()
    evaluation_reason: EvaluationReason = EvaluationReason.NORMAL
    request_id: str | None = None
    correlation_id: str | None = None


class EffectiveEvidenceSet(BaseModel):
    """DE-003 §11's output: at most one usable evidence result per declared,
    non-prohibited evidence type, plus the separately-tracked presence of
    prohibited types.

    Prohibited evidence is kept out of `by_type` deliberately -- it is never
    an eligible decision input, and the only way a policy may react to it is
    an explicit `_present` condition (enforced at policy-activation time by
    core.policy.validation). Undeclared evidence appears in neither field,
    which is how DEC-5.4.3 ("undeclared evidence MUST NOT influence the
    decision") becomes a filter rather than a documented intention.
    """

    by_type: dict[str, EvidenceResult] = Field(default_factory=dict)
    prohibited_types_present: frozenset[str] = frozenset()

    def is_present(self, evidence_type: str) -> bool:
        """Backs the `_present` condition field: true iff at least one
        effective, *declared* evidence result of this type exists. Prohibited
        types count as present -- observability is exactly what `_present`
        exists for -- while undeclared types never do, so that submitting
        undeclared evidence cannot change any decision."""
        return evidence_type in self.by_type or evidence_type in self.prohibited_types_present


def resolve_effective_evidence(
    effective_evidence: tuple[EvidenceResult, ...] | list[EvidenceResult],
    policy: VerificationPolicy,
) -> EffectiveEvidenceSet:
    """DE-003 §11, transcribed: declared -> authorized -> prohibited/usable.

    `resolve_one_effective_per_type` is applied as defence in depth only.
    The primary guarantee that a type has at most one effective result is
    the database's partial unique index
    (ix_evidence_results_one_effective_per_type); this call exists for the
    case that guarantee is bypassed, and it emits an operational integrity
    signal whenever it actually has to choose (DE-003 Amendment B).
    """
    declared = {req.evidence_type: req for req in policy.evidence_requirements}
    authorized = [r for r in effective_evidence if r.evidence_type.value in declared]

    prohibited_present = frozenset(
        r.evidence_type.value
        for r in authorized
        if declared[r.evidence_type.value].level == EvidenceRequirementLevel.PROHIBITED
    )
    usable = [
        r
        for r in authorized
        if declared[r.evidence_type.value].level != EvidenceRequirementLevel.PROHIBITED
    ]

    return EffectiveEvidenceSet(
        by_type={r.evidence_type.value: r for r in resolve_one_effective_per_type(usable)},
        prohibited_types_present=prohibited_present,
    )
