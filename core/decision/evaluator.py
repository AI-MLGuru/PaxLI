"""The pure Decision Engine evaluator (DE-002 §8 pipeline, DE-003 §14).

    DecisionEvaluationContext  ->  evaluate()  ->  DecisionCandidate

Nothing in this module performs I/O, reads a clock, generates an identifier,
or touches a repository. It cannot: it has no session, no repository, and no
imports that would let it. That is deliberate -- DEC-5.25.1-4's determinism
requirements are then structural facts about the module rather than
properties someone has to keep re-verifying by review.

Pipeline, in the frozen order:

    1. context coherence          -> INCONCLUSIVE, engine code
    2. expiration short-circuit   -> INCONCLUSIVE, unconditionally
    3. evidence authorization filter
    4. required-evidence check    -> INCONCLUSIVE / REQUIRED_EVIDENCE_MISSING
    5. calibration compatibility  -> INCONCLUSIVE / CALIBRATION_MODEL_MISMATCH
    6. gates, ascending priority  -> gate's on_failure_outcome
    7. rules, ascending priority  -> rule's outcome
    8. default_outcome, else      -> INCONCLUSIVE / NO_MATCHING_RULE

Step 4 preceding step 6 is DE-002 §8's order, and it is the safer of the two
readings of DEC-5.23's precedence ladder: if required evidence is absent
*because* a provider was UNAVAILABLE, checking gates first could answer
REJECTED to what is partly an infrastructure failure, which DEC-5.23.2
forbids. Required-evidence-first answers INCONCLUSIVE instead.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from core.decision.condition_eval import TruthValue, evaluate_condition
from core.decision.context import (
    DecisionEvaluationContext,
    EffectiveEvidenceSet,
    resolve_effective_evidence,
)
from core.decision.enums import DecisionOutcome, EngineReasonCode, EvaluationReason
from core.decision.models import DecisionCandidate
from core.decision.references import EvidenceReference, PolicyReference
from core.evidence_result.enums import EvidenceResultStatus
from core.evidence_result.models import EvidenceResult, ModelReference
from core.policy.condition import Condition, ThresholdRef, iter_evidence_conditions
from core.policy.models import VerificationPolicy
from core.policy.requirements import EvidenceRequirementLevel
from core.policy.thresholds import ThresholdDefinition

# EVD-3.7: statuses that assert *no result was produced*. A required evidence
# type whose only effective result carries one of these has not been
# satisfied -- EVD-3.18.3 forbids absent required evidence from silently
# becoming NOT_REQUIRED.
#
# INCONCLUSIVE is deliberately NOT in this set. Per EVD-3.7, it means
# processing was attempted and a determination of uncertainty was reached;
# EVD-3.22.4 gives the Decision Engine authority over what that uncertainty
# means, and a policy may legitimately author a rule such as "Liveness
# INCONCLUSIVE -> INCONCLUSIVE". Treating it as missing here would make that
# authorship unreachable.
_UNSATISFYING_STATUSES = frozenset(
    {
        EvidenceResultStatus.NOT_REQUIRED,
        EvidenceResultStatus.NOT_SUBMITTED,
        EvidenceResultStatus.UNAVAILABLE,
    }
)


@dataclass(frozen=True)
class _Conclusion:
    outcome: DecisionOutcome
    reason_codes: tuple[str, ...]


def evaluate(context: DecisionEvaluationContext) -> DecisionCandidate:
    """Produces exactly one DecisionCandidate for a context. Total: every
    path through this function returns a candidate, and no path returns
    VERIFIED except an explicitly matched policy rule."""
    policy = context.policy
    policy_reference = PolicyReference.from_policy(policy)
    thresholds = {t.name: t for t in policy.thresholds}

    incoherent = _check_context_coherence(context)
    if incoherent is not None:
        return _assemble(context, policy_reference, incoherent, evidence_set=None)

    if context.evaluation_reason is EvaluationReason.EXPIRATION:
        # WF-4.6 is unconditional: work completing after the deadline must
        # not produce VERIFIED or REJECTED. This is a workflow invariant, not
        # a policy input, so no gate, rule or default_outcome is consulted --
        # the policy is never given the opportunity to override it.
        return _assemble(
            context,
            policy_reference,
            _Conclusion(
                DecisionOutcome.INCONCLUSIVE,
                (EngineReasonCode.SESSION_EXPIRED_DURING_PROCESSING.value,),
            ),
            evidence_set=None,
        )

    evidence_set = resolve_effective_evidence(context.effective_evidence, policy)

    conclusion = (
        _check_required_evidence(policy, evidence_set, thresholds)
        or _check_calibration_compatibility(policy, evidence_set, thresholds)
        or _evaluate_gates(policy, evidence_set, thresholds)
        or _evaluate_rules(policy, evidence_set, thresholds)
        or _default_conclusion(policy)
    )
    return _assemble(context, policy_reference, conclusion, evidence_set=evidence_set)


def _check_context_coherence(context: DecisionEvaluationContext) -> _Conclusion | None:
    """The part of DE-002 §8 step 1 a pure evaluator can actually perform.
    Re-fetching the pinned policy and confirming its hash belongs to the
    orchestrator, which owns the I/O; what the evaluator can check is that
    the context it was handed is internally consistent -- and a tenant
    mismatch here would mean one tenant's evidence or policy reaching
    another tenant's decision, which is a critical failure, not a decision
    input."""
    if context.policy.tenant_id != context.tenant_id:
        return _Conclusion(DecisionOutcome.INCONCLUSIVE, (EngineReasonCode.POLICY_INVALID.value,))
    for result in context.effective_evidence:
        if result.tenant_id != context.tenant_id or result.session_id != context.session_id:
            return _Conclusion(
                DecisionOutcome.INCONCLUSIVE, (EngineReasonCode.DECISION_ENGINE_ERROR.value,)
            )
    return None


def _check_required_evidence(
    policy: VerificationPolicy,
    evidence_set: EffectiveEvidenceSet,
    thresholds: dict[str, ThresholdDefinition],
) -> _Conclusion | None:
    """DEC-5.5/5.6 + EVD-3.18. A CONDITIONALLY_REQUIRED entry becomes
    required when its trigger condition is TRUE *or* INDETERMINATE: if the
    engine cannot establish that the extra evidence is unnecessary, it
    demands it. Resolving that uncertainty the other way would let an
    unknown trigger quietly excuse missing evidence, which is the optimistic
    fallback DEC-5.23.1 prohibits."""
    for requirement in policy.evidence_requirements:
        if requirement.level == EvidenceRequirementLevel.REQUIRED:
            required = True
        elif requirement.level == EvidenceRequirementLevel.CONDITIONALLY_REQUIRED:
            # EvidenceRequirement's own validator guarantees a condition is
            # present at this level; if one were somehow absent, the trigger
            # is unknowable and the same fail-safe reading applies.
            required = requirement.condition is None or (
                evaluate_condition(
                    requirement.condition, evidence_set=evidence_set, thresholds=thresholds
                )
                is not TruthValue.FALSE
            )
        else:
            continue

        if not required:
            continue
        result = evidence_set.by_type.get(requirement.evidence_type)
        if result is None or result.status in _UNSATISFYING_STATUSES:
            return _Conclusion(
                DecisionOutcome.INCONCLUSIVE,
                (EngineReasonCode.REQUIRED_EVIDENCE_MISSING.value,),
            )
    return None


def _check_calibration_compatibility(
    policy: VerificationPolicy,
    evidence_set: EffectiveEvidenceSet,
    thresholds: dict[str, ThresholdDefinition],
) -> _Conclusion | None:
    """DEC-5.34.2: a threshold calibrated for an incompatible model version
    must not be silently reused.

    Checked as a pre-pass over every threshold the policy actually
    references, not lazily during condition evaluation. Lazily would make
    the outcome depend on which gate or rule happened to match first, so the
    same evidence and policy could produce CALIBRATION_MODEL_MISMATCH or not
    depending on priority ordering -- the implementation-order dependence
    DEC-5.19.1 and DEC-5.25.2 forbid.

    Evidence carrying no model reference at all is also treated as
    incompatible -- frozen and grounded explicitly in
    docs/decisions/DE-003-decision-semantics.md §17.2 (DEC-5.34.1's
    identifiability requirement and DEC-5.34.3's attributability
    requirement, not DEC-5.34.2's "incompatible version" wording alone,
    which is silent on the absent-reference case). Failing safe here costs
    an INCONCLUSIVE; failing open would mean comparing a score against a
    threshold calibrated for something else entirely, and would leave a
    resulting decision structurally unable to satisfy 5.34.3 for that
    evidence. No new ENGINE: code is introduced for this case -- see §17.2
    for how it stays forensically distinguishable from a named
    incompatibility without one.
    """
    for name in sorted(_referenced_threshold_names(policy)):
        definition = thresholds.get(name)
        if definition is None:
            continue
        result = evidence_set.by_type.get(definition.applicable_evidence_type)
        if result is None:
            continue
        model = result.model_reference
        if (
            model is None
            or model.model_id != definition.model_id
            or model.model_version != definition.model_version
        ):
            return _Conclusion(
                DecisionOutcome.INCONCLUSIVE,
                (EngineReasonCode.CALIBRATION_MODEL_MISMATCH.value,),
            )
    return None


def _evaluate_gates(
    policy: VerificationPolicy,
    evidence_set: EffectiveEvidenceSet,
    thresholds: dict[str, ThresholdDefinition],
) -> _Conclusion | None:
    """DEC-5.18: gates are evaluated before any rule, and a gate whose
    condition matches fires (DE-003 §9: "a kind=CONFLICT gate whose condition
    matches"). Ascending priority, lowest-priority match wins -- policy
    validation enforces globally unique priorities, so the order is total
    and never depends on declaration order."""
    for gate in sorted(policy.gates, key=lambda g: g.priority):
        if (
            evaluate_condition(gate.condition, evidence_set=evidence_set, thresholds=thresholds)
            is TruthValue.TRUE
        ):
            return _Conclusion(
                DecisionOutcome(gate.on_failure_outcome), (gate.resolved_reason_code(),)
            )
    return None


def _evaluate_rules(
    policy: VerificationPolicy,
    evidence_set: EffectiveEvidenceSet,
    thresholds: dict[str, ThresholdDefinition],
) -> _Conclusion | None:
    """DEC-5.19: ascending priority, first match wins."""
    for rule in sorted(policy.rules, key=lambda r: r.priority):
        if (
            evaluate_condition(rule.condition, evidence_set=evidence_set, thresholds=thresholds)
            is TruthValue.TRUE
        ):
            return _Conclusion(rule.outcome, (rule.reason_code,))
    return None


def _default_conclusion(policy: VerificationPolicy) -> _Conclusion:
    """DE-003 §10. `NO_MATCHING_RULE` is attached in both branches: the
    outcome differs, but the reason is identically true either way -- nothing
    in the policy addressed this evidence shape. That is also what keeps it
    distinguishable in provenance from UNRESOLVED_EVIDENCE_CONFLICT, which
    means the policy *did* recognise this shape, as a conflict.

    VerificationPolicy rejects `default_outcome == VERIFIED` at construction,
    so this cannot be an optimistic fallback (DEC-5.23.1)."""
    outcome = policy.default_outcome or DecisionOutcome.INCONCLUSIVE
    return _Conclusion(outcome, (EngineReasonCode.NO_MATCHING_RULE.value,))


def _policy_conditions(policy: VerificationPolicy) -> Iterator[Condition]:
    for requirement in policy.evidence_requirements:
        if requirement.condition is not None:
            yield requirement.condition
    for gate in policy.gates:
        yield gate.condition
    for rule in policy.rules:
        yield rule.condition


def _referenced_threshold_names(policy: VerificationPolicy) -> set[str]:
    """Only thresholds a condition actually references can affect a
    decision; an unreferenced ThresholdDefinition is inert."""
    return {
        leaf.expected_value.name
        for condition in _policy_conditions(policy)
        for leaf in iter_evidence_conditions(condition)
        if isinstance(leaf.expected_value, ThresholdRef)
    }


def _distinct_model_references(
    results: Sequence[EvidenceResult],
) -> tuple[ModelReference, ...]:
    seen: set[tuple[object, ...]] = set()
    distinct: list[ModelReference] = []
    for result in results:
        if result.model_reference is None:
            continue
        key = tuple(sorted(result.model_reference.model_dump().items()))
        if key in seen:
            continue
        seen.add(key)
        distinct.append(result.model_reference)
    return tuple(distinct)


def _assemble(
    context: DecisionEvaluationContext,
    policy_reference: PolicyReference,
    conclusion: _Conclusion,
    *,
    evidence_set: EffectiveEvidenceSet | None,
) -> DecisionCandidate:
    """Provenance assembly. `evidence_set is None` marks the paths that
    consumed no evidence at all -- an incoherent context and the expiration
    short-circuit -- where recording evidence references would misrepresent
    what the decision was actually based on.

    Everything is sorted. Provenance that varied by dict or set iteration
    order would make two evaluations of an identical context produce
    non-identical rows, which DEC-5.25.2 forbids.
    """
    if evidence_set is None:
        return DecisionCandidate(
            session_id=context.session_id,
            tenant_id=context.tenant_id,
            outcome=conclusion.outcome,
            reason_codes=conclusion.reason_codes,
            policy_reference=policy_reference,
            evaluation_reason=context.evaluation_reason,
        )

    considered = sorted(evidence_set.by_type.values(), key=lambda r: r.evidence_type.value)
    referenced = _referenced_threshold_names(context.policy)
    calibration_references = sorted(
        {t.calibration_reference for t in context.policy.thresholds if t.name in referenced}
    )

    return DecisionCandidate(
        session_id=context.session_id,
        tenant_id=context.tenant_id,
        outcome=conclusion.outcome,
        reason_codes=conclusion.reason_codes,
        policy_reference=policy_reference,
        evidence_references=tuple(EvidenceReference.from_evidence_result(r) for r in considered),
        model_references=_distinct_model_references(considered),
        calibration_references=tuple(calibration_references),
        prohibited_types_present=tuple(sorted(evidence_set.prohibited_types_present)),
        evaluation_reason=context.evaluation_reason,
    )
