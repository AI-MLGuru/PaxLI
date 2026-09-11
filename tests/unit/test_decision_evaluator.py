"""DE-004 Phase 2: the pure Decision Engine evaluator.

Deliberately database-free. The evaluator is a pure function over a frozen
context, so proving its semantics needs no Postgres, no session, and no
fixtures beyond in-memory domain objects -- and keeping it that way is
itself part of the proof that DEC-5.25's determinism requirements hold by
construction.

Each test names the property from the DE-003 §16 / DE-004 Phase 2 list it
establishes.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from core.decision.context import DecisionEvaluationContext
from core.decision.enums import DecisionOutcome, EngineReasonCode, EvaluationReason
from core.decision.evaluator import evaluate
from core.decision.models import DecisionCandidate
from core.decision.references import PolicyReference
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.models import EvidenceResult, ModelReference
from core.policy.condition import EvidenceCondition, ThresholdRef
from core.policy.enums import PolicyStatus
from core.policy.gates import Gate, GateKind
from core.policy.models import VerificationPolicy
from core.policy.requirements import EvidenceRequirement, EvidenceRequirementLevel
from core.policy.rules import Rule
from core.policy.thresholds import ThresholdDefinition
from core.verification.enums import AssuranceLevel

TENANT = "tenant-a"
SESSION_ID = uuid4()


def _policy(
    *,
    evidence_requirements: tuple[EvidenceRequirement, ...] = (),
    gates: tuple[Gate, ...] = (),
    rules: tuple[Rule, ...] = (),
    thresholds: tuple[ThresholdDefinition, ...] = (),
    default_outcome: DecisionOutcome | None = None,
    tenant_id: str = TENANT,
) -> VerificationPolicy:
    return VerificationPolicy(
        policy_id="policy-standard",
        version=3,
        tenant_id=tenant_id,
        assurance_level=AssuranceLevel.STANDARD,
        status=PolicyStatus.ACTIVE,
        evidence_requirements=evidence_requirements,
        gates=gates,
        rules=rules,
        thresholds=thresholds,
        default_outcome=default_outcome,
        canonical_hash="a" * 64,
        created_by="admin-1",
    )


def _evidence(
    evidence_type: EvidenceResultType = EvidenceResultType.FACE_MATCH,
    *,
    status: EvidenceResultStatus = EvidenceResultStatus.PASS,
    score: float | None = None,
    model_reference: ModelReference | None = None,
    tenant_id: str = TENANT,
    session_id=None,
    produced_at: datetime | None = None,
    integrity_reference: str = "ref",
) -> EvidenceResult:
    return EvidenceResult(
        tenant_id=tenant_id,
        session_id=session_id or SESSION_ID,
        evidence_type=evidence_type,
        status=status,
        score=score,
        model_reference=model_reference,
        producer="p",
        producer_version="1",
        produced_at=produced_at or datetime.now(UTC),
        persisted_at=datetime.now(UTC),
        integrity_reference=integrity_reference,
    )


def _context(policy, *evidence, reason=EvaluationReason.NORMAL) -> DecisionEvaluationContext:
    return DecisionEvaluationContext(
        session_id=SESSION_ID,
        tenant_id=TENANT,
        policy=policy,
        effective_evidence=tuple(evidence),
        evaluation_reason=reason,
    )


def _required(evidence_type: str) -> EvidenceRequirement:
    return EvidenceRequirement(evidence_type=evidence_type, level=EvidenceRequirementLevel.REQUIRED)


def _optional(evidence_type: str) -> EvidenceRequirement:
    return EvidenceRequirement(evidence_type=evidence_type, level=EvidenceRequirementLevel.OPTIONAL)


def _face_status_is(value: str) -> EvidenceCondition:
    return EvidenceCondition(
        evidence_type="FACE_MATCH", field="status", operator="==", expected_value=value
    )


# --------------------------------------------------------------------------
# 1. Policy reference is pinned
# --------------------------------------------------------------------------


def test_policy_reference_is_derived_solely_from_the_supplied_policy() -> None:
    """The evaluator is never handed loose policy_id/version/hash values it
    could combine inconsistently: it derives all three from the one pinned
    policy object in the context. Once the orchestrator supplies the
    session's pinned policy, `Decision.policy_reference ==
    Session.policy_reference` follows structurally -- the bit-for-bit
    equality against a persisted session is proven in Phase 4, where the
    session pin exists."""
    policy = _policy(rules=(), default_outcome=DecisionOutcome.REVIEW_REQUIRED)
    candidate = evaluate(_context(policy))

    assert candidate.policy_reference == PolicyReference.from_policy(policy)
    assert candidate.policy_reference.policy_id == policy.policy_id
    assert candidate.policy_reference.policy_version == policy.version
    assert candidate.policy_reference.policy_hash == policy.canonical_hash


def test_policy_reference_is_pinned_on_every_path_including_short_circuits() -> None:
    policy = _policy(evidence_requirements=(_required("FACE_MATCH"),))
    expected = PolicyReference.from_policy(policy)

    expired = evaluate(_context(policy, reason=EvaluationReason.EXPIRATION))
    missing = evaluate(_context(policy))
    incoherent = evaluate(_context(_policy(tenant_id="tenant-other")))

    assert expired.policy_reference == expected
    assert missing.policy_reference == expected
    assert incoherent.policy_reference.policy_id == policy.policy_id


# --------------------------------------------------------------------------
# 2. Expiration short-circuits everything
# --------------------------------------------------------------------------


def test_expiration_produces_inconclusive_regardless_of_what_policy_would_conclude() -> None:
    """WF-4.6 is unconditional. This policy would otherwise VERIFY on a
    matching rule and REJECT on a firing gate; expiration must override
    both."""
    policy = _policy(
        gates=(
            Gate(
                id="g1",
                kind=GateKind.BLOCKING,
                condition=_face_status_is("PASS"),
                priority=10,
                on_failure_outcome=DecisionOutcome.REJECTED,
                failure_reason_code="POLICY:FACE_MATCH_BLOCKED",
            ),
        ),
        rules=(
            Rule(
                id="r1",
                condition=_face_status_is("PASS"),
                outcome=DecisionOutcome.VERIFIED,
                priority=10,
                reason_code="POLICY:ALL_CHECKS_PASSED",
            ),
        ),
        default_outcome=DecisionOutcome.REJECTED,
    )
    candidate = evaluate(_context(policy, _evidence(), reason=EvaluationReason.EXPIRATION))

    assert candidate.outcome is DecisionOutcome.INCONCLUSIVE
    assert candidate.reason_codes == (EngineReasonCode.SESSION_EXPIRED_DURING_PROCESSING.value,)
    assert candidate.evaluation_reason is EvaluationReason.EXPIRATION


def test_expiration_records_no_evidence_as_consumed() -> None:
    """Nothing was evaluated, so provenance must not claim evidence
    participated in the decision."""
    policy = _policy(evidence_requirements=(_optional("FACE_MATCH"),))
    candidate = evaluate(_context(policy, _evidence(), reason=EvaluationReason.EXPIRATION))
    assert candidate.evidence_references == ()


# --------------------------------------------------------------------------
# 3. Evidence authorization is deterministic
# --------------------------------------------------------------------------


def test_undeclared_evidence_cannot_influence_the_decision() -> None:
    """DEC-5.4.3. Submitting evidence the policy never declared must produce
    the same decision as not submitting it at all."""
    policy = _policy(
        rules=(
            Rule(
                id="r1",
                condition=_face_status_is("PASS"),
                outcome=DecisionOutcome.VERIFIED,
                priority=10,
                reason_code="POLICY:FACE_MATCH_OK",
            ),
        )
    )
    without = evaluate(_context(policy))
    with_undeclared = evaluate(_context(policy, _evidence(status=EvidenceResultStatus.PASS)))

    assert without.outcome is with_undeclared.outcome is DecisionOutcome.INCONCLUSIVE
    assert with_undeclared.reason_codes == (EngineReasonCode.NO_MATCHING_RULE.value,)
    assert with_undeclared.evidence_references == ()


def test_prohibited_evidence_present_does_not_by_itself_reject() -> None:
    """The DE-002 sign-off's exact wording: prohibited evidence is never an
    eligible decision input; its presence may be observed, but it affects
    the outcome only through an explicit policy condition."""
    policy = _policy(
        evidence_requirements=(
            EvidenceRequirement(
                evidence_type="FACE_MATCH", level=EvidenceRequirementLevel.PROHIBITED
            ),
        ),
        default_outcome=DecisionOutcome.REVIEW_REQUIRED,
    )
    candidate = evaluate(_context(policy, _evidence()))

    assert candidate.outcome is DecisionOutcome.REVIEW_REQUIRED
    assert candidate.reason_codes == (EngineReasonCode.NO_MATCHING_RULE.value,)
    # observable in provenance, but never an evaluated input
    assert candidate.prohibited_types_present == ("FACE_MATCH",)
    assert candidate.evidence_references == ()


def test_prohibited_evidence_affects_the_outcome_only_through_an_explicit_present_rule() -> None:
    policy = _policy(
        evidence_requirements=(
            EvidenceRequirement(
                evidence_type="FACE_MATCH", level=EvidenceRequirementLevel.PROHIBITED
            ),
        ),
        rules=(
            Rule(
                id="r1",
                condition=EvidenceCondition(
                    evidence_type="FACE_MATCH",
                    field="_present",
                    operator="==",
                    expected_value=True,
                ),
                outcome=DecisionOutcome.REJECTED,
                priority=10,
                reason_code="POLICY:PROHIBITED_EVIDENCE_SUBMITTED",
            ),
        ),
    )
    fired = evaluate(_context(policy, _evidence()))
    assert fired.outcome is DecisionOutcome.REJECTED
    assert fired.reason_codes == ("POLICY:PROHIBITED_EVIDENCE_SUBMITTED",)

    quiet = evaluate(_context(policy))
    assert quiet.outcome is DecisionOutcome.INCONCLUSIVE


# --------------------------------------------------------------------------
# 4. Required evidence is checked before gates and rules
# --------------------------------------------------------------------------


def test_missing_required_evidence_precedes_a_gate_that_would_otherwise_reject() -> None:
    """DEC-5.23.2: infrastructure failure must not become REJECTED. If the
    required evidence is absent, the engine answers INCONCLUSIVE even though
    a gate would have fired REJECTED on what evidence there is."""
    policy = _policy(
        evidence_requirements=(_required("LIVENESS_ASSESSMENT"), _optional("FACE_MATCH")),
        gates=(
            Gate(
                id="g1",
                kind=GateKind.BLOCKING,
                condition=_face_status_is("FAIL"),
                priority=10,
                on_failure_outcome=DecisionOutcome.REJECTED,
                failure_reason_code="POLICY:FACE_MATCH_FAILED",
            ),
        ),
    )
    candidate = evaluate(_context(policy, _evidence(status=EvidenceResultStatus.FAIL)))

    assert candidate.outcome is DecisionOutcome.INCONCLUSIVE
    assert candidate.reason_codes == (EngineReasonCode.REQUIRED_EVIDENCE_MISSING.value,)


@pytest.mark.parametrize(
    "status",
    [
        EvidenceResultStatus.NOT_SUBMITTED,
        EvidenceResultStatus.UNAVAILABLE,
        EvidenceResultStatus.NOT_REQUIRED,
    ],
)
def test_required_evidence_asserting_no_result_does_not_satisfy_the_requirement(status) -> None:
    """EVD-3.18.3: absent required evidence must not silently become
    NOT_REQUIRED. A provider outage (UNAVAILABLE) is not a satisfied
    requirement."""
    policy = _policy(evidence_requirements=(_required("FACE_MATCH"),))
    candidate = evaluate(_context(policy, _evidence(status=status)))
    assert candidate.reason_codes == (EngineReasonCode.REQUIRED_EVIDENCE_MISSING.value,)


def test_inconclusive_required_evidence_reaches_policy_rather_than_counting_as_missing() -> None:
    """EVD-3.22.4 gives the Decision Engine authority over the consequence of
    inconclusive evidence, and a policy may legitimately author that
    consequence. Treating INCONCLUSIVE as missing would make such a rule
    unreachable."""
    policy = _policy(
        evidence_requirements=(_required("FACE_MATCH"),),
        rules=(
            Rule(
                id="r1",
                condition=_face_status_is("INCONCLUSIVE"),
                outcome=DecisionOutcome.REVIEW_REQUIRED,
                priority=10,
                reason_code="POLICY:FACE_MATCH_UNCERTAIN",
            ),
        ),
    )
    candidate = evaluate(_context(policy, _evidence(status=EvidenceResultStatus.INCONCLUSIVE)))

    assert candidate.outcome is DecisionOutcome.REVIEW_REQUIRED
    assert candidate.reason_codes == ("POLICY:FACE_MATCH_UNCERTAIN",)


def test_conditionally_required_evidence_with_an_unknowable_trigger_is_demanded() -> None:
    """Fail-safe: if the engine cannot establish that the extra evidence is
    unnecessary, it demands it rather than quietly excusing it."""
    policy = _policy(
        evidence_requirements=(
            EvidenceRequirement(
                evidence_type="LIVENESS_ASSESSMENT",
                level=EvidenceRequirementLevel.CONDITIONALLY_REQUIRED,
                # trigger references evidence that is absent -> INDETERMINATE
                condition=_face_status_is("FAIL"),
            ),
        ),
    )
    candidate = evaluate(_context(policy))
    assert candidate.reason_codes == (EngineReasonCode.REQUIRED_EVIDENCE_MISSING.value,)


def test_conditionally_required_evidence_with_a_false_trigger_is_not_demanded() -> None:
    policy = _policy(
        evidence_requirements=(
            _optional("FACE_MATCH"),
            EvidenceRequirement(
                evidence_type="LIVENESS_ASSESSMENT",
                level=EvidenceRequirementLevel.CONDITIONALLY_REQUIRED,
                condition=_face_status_is("FAIL"),
            ),
        ),
        default_outcome=DecisionOutcome.REVIEW_REQUIRED,
    )
    candidate = evaluate(_context(policy, _evidence(status=EvidenceResultStatus.PASS)))
    assert candidate.outcome is DecisionOutcome.REVIEW_REQUIRED
    assert candidate.reason_codes == (EngineReasonCode.NO_MATCHING_RULE.value,)


# --------------------------------------------------------------------------
# 5-6. Gate ordering and conflict semantics
# --------------------------------------------------------------------------


def _gate(gate_id: str, priority: int, outcome: DecisionOutcome, code: str) -> Gate:
    return Gate(
        id=gate_id,
        kind=GateKind.BLOCKING,
        condition=_face_status_is("FAIL"),
        priority=priority,
        on_failure_outcome=outcome,
        failure_reason_code=code,
    )


def test_lowest_priority_gate_wins_regardless_of_declaration_order() -> None:
    """DEC-5.19.1 applied to gates: ordering must not depend on
    implementation iteration order."""
    low = _gate("low", 10, DecisionOutcome.REJECTED, "POLICY:LOW_PRIORITY_GATE")
    high = _gate("high", 20, DecisionOutcome.REVIEW_REQUIRED, "POLICY:HIGH_PRIORITY_GATE")
    evidence = _evidence(status=EvidenceResultStatus.FAIL)
    requirements = (_optional("FACE_MATCH"),)

    forward = evaluate(
        _context(_policy(evidence_requirements=requirements, gates=(low, high)), evidence)
    )
    reverse = evaluate(
        _context(_policy(evidence_requirements=requirements, gates=(high, low)), evidence)
    )

    assert forward.outcome is reverse.outcome is DecisionOutcome.REJECTED
    assert forward.reason_codes == reverse.reason_codes == ("POLICY:LOW_PRIORITY_GATE",)


def test_a_fired_gate_is_not_overridden_by_a_matching_rule() -> None:
    """DEC-5.18.1/5.18.2: gates evaluate before any rule, and a failed
    blocking gate is not overridden."""
    policy = _policy(
        evidence_requirements=(_optional("FACE_MATCH"),),
        gates=(_gate("g1", 10, DecisionOutcome.REJECTED, "POLICY:FACE_MATCH_FAILED"),),
        rules=(
            Rule(
                id="r1",
                condition=_face_status_is("FAIL"),
                outcome=DecisionOutcome.VERIFIED,
                priority=10,
                reason_code="POLICY:SOMEHOW_VERIFIED",
            ),
        ),
    )
    candidate = evaluate(_context(policy, _evidence(status=EvidenceResultStatus.FAIL)))
    assert candidate.outcome is DecisionOutcome.REJECTED


def test_conflict_gate_without_a_reason_code_uses_the_engine_conflict_code() -> None:
    """DE-003 Amendment A's CONFLICT branch."""
    policy = _policy(
        evidence_requirements=(_optional("FACE_MATCH"),),
        gates=(
            Gate(
                id="conflict-1",
                kind=GateKind.CONFLICT,
                condition=_face_status_is("FAIL"),
                priority=10,
                on_failure_outcome=DecisionOutcome.INCONCLUSIVE,
            ),
        ),
    )
    candidate = evaluate(_context(policy, _evidence(status=EvidenceResultStatus.FAIL)))

    assert candidate.outcome is DecisionOutcome.INCONCLUSIVE
    assert candidate.reason_codes == (EngineReasonCode.UNRESOLVED_EVIDENCE_CONFLICT.value,)


def test_blocking_gate_without_a_reason_code_is_unconstructable() -> None:
    """Amendment A's BLOCKING branch, enforced at construction so an
    ambiguous decision is impossible rather than merely unlikely."""
    with pytest.raises(ValueError, match="failure_reason_code is required"):
        Gate(
            id="g1",
            kind=GateKind.BLOCKING,
            condition=_face_status_is("FAIL"),
            priority=10,
            on_failure_outcome=DecisionOutcome.REJECTED,
        )


def test_indeterminate_gate_condition_does_not_fire() -> None:
    """A gate whose condition cannot be evaluated must neither fire nor be
    treated as passed-with-certainty; evaluation continues to the rules, and
    the absent evidence surfaces through the ordinary no-match path."""
    policy = _policy(
        gates=(_gate("g1", 10, DecisionOutcome.REJECTED, "POLICY:FACE_MATCH_FAILED"),),
    )
    candidate = evaluate(_context(policy))
    assert candidate.reason_codes == (EngineReasonCode.NO_MATCHING_RULE.value,)


# --------------------------------------------------------------------------
# 7. Rules: ascending priority, first match
# --------------------------------------------------------------------------


def test_first_matching_rule_by_ascending_priority_wins() -> None:
    first = Rule(
        id="r-first",
        condition=_face_status_is("PASS"),
        outcome=DecisionOutcome.VERIFIED,
        priority=10,
        reason_code="POLICY:FIRST_MATCH",
    )
    second = Rule(
        id="r-second",
        condition=_face_status_is("PASS"),
        outcome=DecisionOutcome.REVIEW_REQUIRED,
        priority=20,
        reason_code="POLICY:SECOND_MATCH",
    )
    evidence = _evidence(status=EvidenceResultStatus.PASS)
    requirements = (_required("FACE_MATCH"),)

    forward = evaluate(
        _context(_policy(evidence_requirements=requirements, rules=(first, second)), evidence)
    )
    reverse = evaluate(
        _context(_policy(evidence_requirements=requirements, rules=(second, first)), evidence)
    )

    assert forward.outcome is reverse.outcome is DecisionOutcome.VERIFIED
    assert forward.reason_codes == reverse.reason_codes == ("POLICY:FIRST_MATCH",)


def test_verified_requires_an_explicitly_matched_rule() -> None:
    """The constitutional rule: VERIFIED is only ever reached through
    explicit policy evaluation, never as a fallback."""
    policy = _policy(evidence_requirements=(_required("FACE_MATCH"),))
    candidate = evaluate(_context(policy, _evidence(status=EvidenceResultStatus.PASS)))
    assert candidate.outcome is not DecisionOutcome.VERIFIED


# --------------------------------------------------------------------------
# 8. default_outcome=VERIFIED is impossible
# --------------------------------------------------------------------------


def test_default_outcome_verified_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="not permitted"):
        _policy(default_outcome=DecisionOutcome.VERIFIED)


def test_declared_default_outcome_is_used_when_nothing_matches() -> None:
    policy = _policy(default_outcome=DecisionOutcome.REJECTED)
    candidate = evaluate(_context(policy))
    assert candidate.outcome is DecisionOutcome.REJECTED
    assert candidate.reason_codes == (EngineReasonCode.NO_MATCHING_RULE.value,)


def test_absent_default_outcome_falls_to_inconclusive() -> None:
    candidate = evaluate(_context(_policy()))
    assert candidate.outcome is DecisionOutcome.INCONCLUSIVE
    assert candidate.reason_codes == (EngineReasonCode.NO_MATCHING_RULE.value,)


# --------------------------------------------------------------------------
# 9. Calibration / model-version mismatch
# --------------------------------------------------------------------------


def _calibrated_policy(model_version: str) -> VerificationPolicy:
    return _policy(
        evidence_requirements=(_required("FACE_MATCH"),),
        thresholds=(
            ThresholdDefinition(
                name="face_match_min",
                value=0.75,
                model_id="face-v1",
                model_version=model_version,
                calibration_reference="cal-2026-01",
                applicable_evidence_type="FACE_MATCH",
            ),
        ),
        rules=(
            Rule(
                id="r1",
                condition=EvidenceCondition(
                    evidence_type="FACE_MATCH",
                    field="score",
                    operator=">=",
                    expected_value=ThresholdRef(name="face_match_min"),
                ),
                outcome=DecisionOutcome.VERIFIED,
                priority=10,
                reason_code="POLICY:FACE_MATCH_ABOVE_THRESHOLD",
            ),
        ),
    )


def test_matching_model_version_evaluates_the_threshold_normally() -> None:
    policy = _calibrated_policy("1.0.0")
    evidence = _evidence(
        score=0.9, model_reference=ModelReference(model_id="face-v1", model_version="1.0.0")
    )
    candidate = evaluate(_context(policy, evidence))

    assert candidate.outcome is DecisionOutcome.VERIFIED
    assert candidate.calibration_references == ("cal-2026-01",)


def test_stale_model_version_produces_calibration_model_mismatch() -> None:
    """DEC-5.34.2: a threshold calibrated for an incompatible model version
    must not be silently reused. Note the evidence would otherwise VERIFY --
    the mismatch must be worth more than a comfortable answer."""
    policy = _calibrated_policy("2.0.0")
    evidence = _evidence(
        score=0.9, model_reference=ModelReference(model_id="face-v1", model_version="1.0.0")
    )
    candidate = evaluate(_context(policy, evidence))

    assert candidate.outcome is DecisionOutcome.INCONCLUSIVE
    assert candidate.reason_codes == (EngineReasonCode.CALIBRATION_MODEL_MISMATCH.value,)


def test_different_model_id_also_produces_calibration_model_mismatch() -> None:
    """ "Incompatible model" in DEC-5.34.2 covers a different model, not only
    a different version of the same one."""
    policy = _calibrated_policy("1.0.0")
    evidence = _evidence(
        score=0.9, model_reference=ModelReference(model_id="face-v2", model_version="1.0.0")
    )
    assert evaluate(_context(policy, evidence)).reason_codes == (
        EngineReasonCode.CALIBRATION_MODEL_MISMATCH.value,
    )


def test_evidence_with_no_model_reference_cannot_satisfy_a_calibrated_threshold() -> None:
    """Fail-safe: evidence that cannot demonstrate which model produced it
    cannot demonstrate that the threshold applies to it."""
    policy = _calibrated_policy("1.0.0")
    candidate = evaluate(_context(policy, _evidence(score=0.9, model_reference=None)))
    assert candidate.reason_codes == (EngineReasonCode.CALIBRATION_MODEL_MISMATCH.value,)


def test_calibration_check_does_not_depend_on_which_rule_would_match_first() -> None:
    """The check is a pre-pass, not lazy: were it evaluated only when a
    condition happened to be reached, the same evidence and policy would
    produce a mismatch or not depending on rule priority ordering."""
    policy = _calibrated_policy("2.0.0")
    shadowing_rule = Rule(
        id="r0",
        condition=_face_status_is("PASS"),
        outcome=DecisionOutcome.VERIFIED,
        priority=1,
        reason_code="POLICY:SHORT_CIRCUIT",
    )
    shadowed = policy.model_copy(update={"rules": (shadowing_rule, *policy.rules)})
    evidence = _evidence(
        score=0.9,
        status=EvidenceResultStatus.PASS,
        model_reference=ModelReference(model_id="face-v1", model_version="1.0.0"),
    )
    candidate = evaluate(_context(shadowed, evidence))

    assert candidate.outcome is DecisionOutcome.INCONCLUSIVE
    assert candidate.reason_codes == (EngineReasonCode.CALIBRATION_MODEL_MISMATCH.value,)


# --------------------------------------------------------------------------
# 10-11. Reason-code namespaces stay distinguishable
# --------------------------------------------------------------------------


def test_no_matching_rule_is_distinguishable_from_unresolved_conflict() -> None:
    """Both produce INCONCLUSIVE; the reason codes must record which
    happened. NO_MATCHING_RULE means the policy never addressed this
    evidence shape; UNRESOLVED_EVIDENCE_CONFLICT means it explicitly
    recognised it as a conflict."""
    nothing_matched = evaluate(_context(_policy()))
    conflict_policy = _policy(
        evidence_requirements=(_optional("FACE_MATCH"),),
        gates=(
            Gate(
                id="c1",
                kind=GateKind.CONFLICT,
                condition=_face_status_is("FAIL"),
                priority=10,
                on_failure_outcome=DecisionOutcome.INCONCLUSIVE,
            ),
        ),
    )
    conflicted = evaluate(_context(conflict_policy, _evidence(status=EvidenceResultStatus.FAIL)))

    assert nothing_matched.outcome is conflicted.outcome is DecisionOutcome.INCONCLUSIVE
    assert nothing_matched.reason_codes != conflicted.reason_codes


@pytest.mark.parametrize("code", [c.value for c in EngineReasonCode])
def test_a_policy_author_cannot_claim_an_engine_reason_code(code) -> None:
    """DE-003 §7: the two namespaces must not overlap, so a policy can never
    make a deliberate authorship decision look like an engine safe-failure."""
    with pytest.raises(ValueError, match="not a valid POLICY: reason code"):
        Rule(
            id="r1",
            condition=_face_status_is("PASS"),
            outcome=DecisionOutcome.REJECTED,
            priority=10,
            reason_code=code,
        )


def test_every_engine_reason_code_the_evaluator_emits_is_in_the_closed_namespace() -> None:
    engine_codes = {c.value for c in EngineReasonCode}
    for candidate in (
        evaluate(_context(_policy())),
        evaluate(_context(_policy(), reason=EvaluationReason.EXPIRATION)),
        evaluate(_context(_policy(evidence_requirements=(_required("FACE_MATCH"),)))),
        evaluate(_context(_policy(tenant_id="tenant-other"))),
    ):
        for code in candidate.reason_codes:
            assert code in engine_codes
            assert code.startswith("ENGINE:")


# --------------------------------------------------------------------------
# 12. Duplicate evidence cannot create ambiguous evaluation
# --------------------------------------------------------------------------


def test_duplicate_effective_evidence_resolves_deterministically() -> None:
    """DE-003 Amendment B, exercised through the evaluator rather than the
    resolver in isolation: the database's partial unique index makes this
    state unreachable in practice, but if it is ever reached the evaluation
    must still be total and order-independent."""
    older = _evidence(
        status=EvidenceResultStatus.FAIL,
        produced_at=datetime.now(UTC) - timedelta(seconds=5),
        integrity_reference="older",
    )
    newer = _evidence(
        status=EvidenceResultStatus.PASS,
        produced_at=datetime.now(UTC),
        integrity_reference="newer",
    )
    policy = _policy(
        evidence_requirements=(_required("FACE_MATCH"),),
        rules=(
            Rule(
                id="r1",
                condition=_face_status_is("PASS"),
                outcome=DecisionOutcome.VERIFIED,
                priority=10,
                reason_code="POLICY:FACE_MATCH_OK",
            ),
        ),
    )

    forward = evaluate(_context(policy, older, newer))
    reverse = evaluate(_context(policy, newer, older))

    assert forward.outcome is reverse.outcome is DecisionOutcome.VERIFIED
    assert forward.evidence_references == reverse.evidence_references
    assert len(forward.evidence_references) == 1
    assert forward.evidence_references[0].evidence_result_id == newer.id


# --------------------------------------------------------------------------
# Context coherence, provenance, determinism
# --------------------------------------------------------------------------


def test_a_policy_belonging_to_another_tenant_never_produces_a_decision() -> None:
    candidate = evaluate(_context(_policy(tenant_id="tenant-other")))
    assert candidate.outcome is DecisionOutcome.INCONCLUSIVE
    assert candidate.reason_codes == (EngineReasonCode.POLICY_INVALID.value,)


def test_evidence_from_another_tenant_or_session_never_produces_a_decision() -> None:
    policy = _policy(evidence_requirements=(_optional("FACE_MATCH"),))

    cross_tenant = evaluate(_context(policy, _evidence(tenant_id="tenant-other")))
    cross_session = evaluate(_context(policy, _evidence(session_id=uuid4())))

    for candidate in (cross_tenant, cross_session):
        assert candidate.outcome is DecisionOutcome.INCONCLUSIVE
        assert candidate.reason_codes == (EngineReasonCode.DECISION_ENGINE_ERROR.value,)
        assert candidate.evidence_references == ()


def test_provenance_records_the_evidence_and_models_actually_considered() -> None:
    model = ModelReference(model_id="face-v1", model_version="1.0.0")
    evidence = _evidence(score=0.9, model_reference=model)
    policy = _policy(
        evidence_requirements=(_required("FACE_MATCH"),),
        default_outcome=DecisionOutcome.REVIEW_REQUIRED,
    )
    candidate = evaluate(_context(policy, evidence))

    assert len(candidate.evidence_references) == 1
    reference = candidate.evidence_references[0]
    assert reference.evidence_result_id == evidence.id
    assert reference.evidence_type == "FACE_MATCH"
    assert reference.status == "PASS"
    assert reference.integrity_reference == evidence.integrity_reference
    assert candidate.model_references == (model,)


def test_provenance_carries_no_evidence_payload() -> None:
    """PRV-11.30.1: a decision is not a place to duplicate biometric or
    document content. The soft reference is a snapshot of identity and
    status, never of the result payload."""
    evidence = _evidence(score=0.9)
    evidence = evidence.model_copy(update={"result": {"similarity": 0.9}})
    policy = _policy(evidence_requirements=(_required("FACE_MATCH"),))
    candidate = evaluate(_context(policy, evidence))

    serialized = candidate.model_dump_json()
    assert "similarity" not in serialized
    assert not hasattr(candidate.evidence_references[0], "result")


def test_identical_contexts_produce_identical_candidates() -> None:
    """DEC-5.25: same session context, same evidence, same policy version ->
    same decision, byte-for-byte including provenance ordering."""
    policy = _calibrated_policy("1.0.0")
    evidence = _evidence(
        score=0.9, model_reference=ModelReference(model_id="face-v1", model_version="1.0.0")
    )
    first = evaluate(_context(policy, evidence))
    second = evaluate(_context(policy, evidence))
    assert first.model_dump_json() == second.model_dump_json()


def test_candidate_carries_no_identifier_or_timestamp_the_evaluator_could_invent() -> None:
    """The structural half of DEC-5.25.1: the evaluator has no clock and no
    identifier to depend on, because a candidate has nowhere to put one."""
    fields = set(DecisionCandidate.model_fields)
    assert "decision_id" not in fields
    assert "created_at" not in fields


def test_every_path_produces_exactly_one_candidate_and_an_outcome() -> None:
    policy = _calibrated_policy("2.0.0")
    contexts = [
        _context(_policy()),
        _context(_policy(tenant_id="tenant-other")),
        _context(_policy(), reason=EvaluationReason.EXPIRATION),
        _context(_policy(evidence_requirements=(_required("FACE_MATCH"),))),
        _context(policy, _evidence(score=0.9)),
    ]
    for context in contexts:
        candidate = evaluate(context)
        assert isinstance(candidate.outcome, DecisionOutcome)
        assert candidate.reason_codes
        assert candidate.engine_version
