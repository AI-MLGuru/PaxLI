# DE-003 — Decision Engine Semantic Specification Freeze

**Status: FROZEN / APPROVED FOR DE-004 IMPLEMENTATION**

This is the authoritative, durable record of the Decision Engine's semantic
contract, as frozen during the DE-001→DE-004 reconciliation track (which
predates this file and previously existed only in conversation history).
It is a normative implementation dependency for `core/decision/` and
`core/policy/`: DE-004 and every later phase of Decision Engine work must
treat this document as source of truth, on equal footing with
`docs/specification/part-05-decision-engine.md` and
`docs/specification/part-03-evidence-semantics.md`, which it interprets and
makes concrete.

**Scope note**: DE-001 was a read-only reconciliation of all 113 DEC-*
requirements against the existing codebase and Parts II–XI. DE-002 was the
resulting domain/policy semantics design (landmines + proposed resolutions,
not yet frozen). DE-003 is that design's specification freeze, incorporating
sign-off review and two amendments. Neither DE-001 nor DE-002's working
notes are reproduced here; only the frozen result is durable. This file may
be extended by later addenda (as §17 already has been, once), but its core
sections 1–16 below are **not to be reopened** casually — a change here is
an architectural decision with the same weight as amending the normative
specification itself, and should be treated with the same deliberation.

Implementation mandate (unchanged from the original authorization):

> Do not reinterpret or redesign any DE-003 semantic. Transcribe it. If the
> existing codebase cannot represent a requirement, stop and report the
> conflict rather than inventing semantics.

---

## 1–2. Policy grammar and Condition operand model

```
ConditionOperand = Literal | ThresholdRef
Literal = bool | int | float | str
ThresholdRef: type: "threshold_ref" = "threshold_ref"; name: str

EvidenceCondition:
    type: "evidence_condition" = "evidence_condition"
    evidence_type: str
    field: str                    # "status" | "score" | "quality" | "_present" | type-specific field
    operator: "==" | "!=" | ">=" | "<=" | ">" | "<"
    expected_value: ConditionOperand
```

`AllOf`/`AnyOf`/`Not` unchanged from the existing, already-proven tree.

**Validation additions to the existing DEC-5.9/5.10 pipeline:**
- `field == "_present"` is legal for every `evidence_type`, at every
  requirement level, and evaluates `True` iff at least one effective
  `EvidenceResult` of that type exists for the session — the sole legal
  field for `PROHIBITED`-level types (below).
- `field != "_present"` on a `PROHIBITED`-level evidence_type →
  `InvalidPolicyError` at activation time. This is how "cannot satisfy a
  requirement, cannot contribute a score" becomes structurally enforced
  rather than evaluator-runtime-skipped.
- `expected_value` as `ThresholdRef{name}` → cross-check
  `ThresholdDefinition.applicable_evidence_type ==
  EvidenceCondition.evidence_type`, reject on mismatch at activation time
  (extends DEC-5.9.2's "unsupported condition types must be rejected before
  activation" to threshold references).

## 3. EvidenceRequirement (exact)

```
EvidenceRequirementLevel = REQUIRED | OPTIONAL | PROHIBITED | CONDITIONALLY_REQUIRED
EvidenceRequirement:
    evidence_type: str            # validated against EvidenceSchemaCatalog
    level: EvidenceRequirementLevel
    condition: Condition | None   # required iff level == CONDITIONALLY_REQUIRED, forbidden otherwise
```

`evidence_requirements: tuple[EvidenceRequirement, ...]`, one entry per
declared `evidence_type` — duplicate `evidence_type` entries rejected at
activation.

## 4. Gate (exact, with the conflict-diagnosis mechanism)

```
GateKind = BLOCKING | CONFLICT
Gate:
    id: str
    kind: GateKind
    condition: Condition
    priority: int                 # globally unique among gates in the policy
    on_failure_outcome: REJECTED | REVIEW_REQUIRED | INCONCLUSIVE
    failure_reason_code: str | None   # POLICY: code; see Amendment A
```

`kind=CONFLICT` is how a policy author marks "this condition represents
evidence that materially disagrees with itself" as opposed to an ordinary
blocking rule. `NO_MATCHING_RULE` and `UNRESOLVED_EVIDENCE_CONFLICT` are
mechanically distinguishable — the first means nothing in the policy
addressed this evidence shape at all; the second means the policy
explicitly recognized a conflict pattern here and this is what firing looks
like. Both remain policy-authored recognitions, never an engine-invented
heuristic — "evidence describes, policy interprets."

`on_failure_outcome` excludes `VERIFIED` (a gate cannot produce the outcome
it exists to gate) but **includes** `INCONCLUSIVE` — a policy author
deliberately routing a recognized conflict to `INCONCLUSIVE` is authorship,
not engine failure, and needs to be expressible.

## 5. Rule (exact)

```
Rule:
    id: str
    condition: Condition
    outcome: VERIFIED | REJECTED | REVIEW_REQUIRED | INCONCLUSIVE
    priority: int                 # globally unique among rules in the policy
    reason_code: str              # POLICY: code, required (no default)
```

Evaluation: ascending-priority first match.

## 6. ThresholdDefinition (exact)

```
ThresholdDefinition:
    name: str                     # unique within policy, referenced by ThresholdRef
    value: float
    model_id: str
    model_version: str
    calibration_reference: str
    applicable_evidence_type: str
```

## 7. Policy reason-code format (exact)

```
Pattern: ^POLICY:[A-Z][A-Z0-9_]{1,62}$        (2-63 chars after the prefix)
```

Validated at policy activation (extends `validate_policy_content`):
- Matches the pattern exactly.
- Does not collide with any `ENGINE:` value.
- Immutable once the policy version is ACTIVE — a rollback/new-version may
  reuse or change codes freely (new version = new authorship), but nothing
  rewrites what an already-ACTIVE version's codes mean (Invariant 07
  applied to this one field).

## 8. Engine reason-code enum (exact, closed)

```python
class EngineReasonCode(StrEnum):
    DECISION_ENGINE_ERROR = "ENGINE:DECISION_ENGINE_ERROR"
    POLICY_INVALID = "ENGINE:POLICY_INVALID"
    POLICY_VERSION_UNAVAILABLE = "ENGINE:POLICY_VERSION_UNAVAILABLE"
    REQUIRED_EVIDENCE_MISSING = "ENGINE:REQUIRED_EVIDENCE_MISSING"
    EVIDENCE_SCHEMA_INVALID = "ENGINE:EVIDENCE_SCHEMA_INVALID"
    DECISION_TIMEOUT = "ENGINE:DECISION_TIMEOUT"
    SESSION_EXPIRED_DURING_PROCESSING = "ENGINE:SESSION_EXPIRED_DURING_PROCESSING"
    CALIBRATION_MODEL_MISMATCH = "ENGINE:CALIBRATION_MODEL_MISMATCH"
    NO_MATCHING_RULE = "ENGINE:NO_MATCHING_RULE"
    UNRESOLVED_EVIDENCE_CONFLICT = "ENGINE:UNRESOLVED_EVIDENCE_CONFLICT"
```

`POLICY_NOT_FOUND` is deliberately **not** a member — it's a
session-creation-time API error, never a member of a `Decision.reason_codes`
tuple, since under early binding no decision-bearing session can exist
without a resolved policy. Kept in the same closed-vocabulary discipline for
the API error contract, just a different namespace of usage.

This vocabulary is closed. §17 confirms no member was added by the Phase 2
calibration-provenance addendum, despite surfacing a case DE-003 did not
originally enumerate.

## 9. Conflict semantics (exact)

- A conflict exists in the system's vocabulary **only** where a policy
  author wrote a `kind=CONFLICT` gate whose condition matches. There is no
  engine-side contradiction detection beyond that.
- Firing → `on_failure_outcome`, reason code = `failure_reason_code` if set,
  else `ENGINE:UNRESOLVED_EVIDENCE_CONFLICT`.
- No `CONFLICT`-kind gate matches, and no rule matches either →
  `ENGINE:NO_MATCHING_RULE` (policy incompleteness, not a recognized
  conflict).

## 10. Default-outcome semantics (exact)

```
Policy.default_outcome: REJECTED | REVIEW_REQUIRED | INCONCLUSIVE | None
```

Must be explicitly set or explicitly absent — no implicit value. No rule
matches (and no gate fired) → `default_outcome` if present, else
`INCONCLUSIVE` / `ENGINE:NO_MATCHING_RULE`. `VERIFIED` is rejected by schema
validation if ever supplied here — not merely discouraged, a
policy-activation failure (`InvalidPolicyError`).

## 11. Effective-evidence algorithm (exact)

```
resolve_effective_evidence(session, policy):
    results = list_effective_for_session(session.id, session.tenant_id)   # supersession-filtered
    declared = {req.evidence_type: req for req in policy.evidence_requirements}
    authorized = [r for r in results if r.evidence_type in declared]
    prohibited_present = {r.evidence_type for r in authorized
                           if declared[r.evidence_type].level == PROHIBITED}
    usable = [r for r in authorized
              if declared[r.evidence_type].level != PROHIBITED]
    return EffectiveEvidenceSet(by_type=group_by_type(usable),
                                 prohibited_types_present=prohibited_present)
```

**Duplicate-evidence-type finding, resolved two-part**: nothing prevents two
independent, non-superseding `EvidenceResult` rows of the same
`evidence_type` for one session by default. Resolution:

- **(a) Primary invariant**: a database constraint enforcing at most one
  non-superseded `EvidenceResult` per `(tenant_id, session_id,
  evidence_type)` — the same shape as Policy's partial-unique-index-per-
  assurance-level. Implemented as `is_effective` +
  `ix_evidence_results_one_effective_per_type` (DE-004 Phase 1).
- **(b) Defensive fallback (Amendment B)**: the algorithm still defensively
  defines a deterministic winner for the case where (a) is somehow bypassed
  (a bug, a manual DB edit, a migration window) — see Amendment B below.

## 12. DecisionResult / provenance (exact, with `policy_hash` promoted)

```
PolicyReference: policy_id: str; policy_version: int; policy_hash: str

EvidenceReference:
    evidence_result_id: UUID; evidence_type: str
    status: str; integrity_reference: str

DecisionResult:
    decision_id: UUID; session_id: UUID; tenant_id: str
    outcome: VERIFIED | REJECTED | REVIEW_REQUIRED | INCONCLUSIVE
    reason_codes: tuple[str, ...]
    policy_reference: PolicyReference
    created_at: datetime

DecisionProvenance (same row, fuller projection):
    ... all DecisionResult fields ...
    evidence_references: tuple[EvidenceReference, ...]
    model_references: tuple[ModelReference, ...]
    calibration_references: tuple[str, ...]
    evaluation_reason: NORMAL | EXPIRATION
    engine_version: str
```

Explicit semantic rule, verbatim as the contract: `evidence_result_id`
identifies the historical evidence object that participated; the snapshot
fields are the authoritative historical record of what the engine observed.
If the live row is later deleted, the decision does not become incomplete —
nothing in `DecisionResult`/`DecisionProvenance` is re-derived from a live
lookup, ever.

**Named property**: `Decision.policy_reference == Session.policy_reference`
for every decision, unconditionally — since early binding means the
session's pin *is* what gets evaluated, these must be bit-for-bit identical,
and a mismatch is itself a detectable bug class worth its own test.

## 13. Evaluation state machine (exact)

Six terminal states, unchanged from existing `VerificationStatus`:
`VERIFIED, REJECTED, REVIEW_REQUIRED, INCONCLUSIVE, EXPIRED, CANCELLED`.
Non-terminal: `CREATED, CAPTURING, SUBMITTED, PROCESSING`.

```
Evidence submission legal  iff  session.status ∈ {CREATED, CAPTURING, SUBMITTED, PROCESSING}
Evidence submission illegal iff session.status ∈ {VERIFIED, REJECTED, REVIEW_REQUIRED,
                                                    INCONCLUSIVE, EXPIRED, CANCELLED}
```

This is the literal guard `EvidenceService.add()` must implement — a
mandatory DE-004 acceptance criterion: no implementation is complete until
submission is rejected for all six terminal states, proven against real
Postgres.

What drives `CREATED → PROCESSING`, and what calls the evaluator, is
explicitly **out of scope** here — that's orchestration, not Decision
Engine semantics. DE-003 only fixes the evaluator's own contract: given a
`DecisionEvaluationContext`, produce exactly one `DecisionResult`, once,
ever, per session.

## 14. Transaction boundary (exact)

```
1. Evaluator (pure, no I/O) produces a candidate (outcome, reason_codes, provenance) — in memory only, nothing durable yet
2. Service opens one transaction:
   a. INSERT DecisionResult/Provenance row  (UNIQUE(tenant_id, session_id) is the idempotency backstop)
   b. record REQUIRED audit event, same transaction
   c. COMMIT
3. If (a) violates the unique constraint → DecisionAlreadyExistsError → caller fetches the existing row, treats as success (concurrent-evaluation case, already-proven pattern)
4. If (b)'s audit write fails → whole transaction rolls back → no row (a) either
5. A later retry re-runs from step 1 and converges via step 3's idempotency, or completes cleanly if nothing exists yet
```

Crisp invariant: **no externally durable decision without its required
audit event.** Identical shape to Evidence-deletion reconciliation — same
idempotent-retry-after-partial-failure property, same reason it works.

`EXPIRATION` context short-circuits *before* step 1's gate/rule evaluation
even runs — it is a workflow invariant, not a policy condition; no gate,
rule, or `default_outcome` is ever consulted once `evaluation_reason ==
EXPIRATION`.

## 15. DEC-5.1-5.35 traceability (complete)

| Requirement(s) | Disposition |
|---|---|
| 5.1.1-3, 5.2.1-3 | Structural: evaluator is the only writer of `DecisionResult`; no other component constructs one |
| 5.3.1-3 | `DecisionResult.outcome`, existing `VerificationStatus` overlap unchanged |
| 5.4.1 | §1 early binding — pinned `PolicyReference` |
| 5.4.2-3 | §11 effective-evidence algorithm's `declared`/`authorized` filter |
| 5.4.4 | §12 `DecisionProvenance` |
| 5.5.1-3, 5.6.1-3 | §3 `EvidenceRequirement` |
| 5.7.1-3 | Unchanged — existing `EvidenceResultStatus`/`classify()` already faithful |
| 5.8.1-4, 5.9.1-3, 5.10.1-3, 5.11.1-3, 5.12.1-4 | Unchanged — Foundation-009, already conformant |
| 5.13.1-4, 5.14.1-3, 5.15.1-2, 5.16.1-2 | Unchanged tree + §2 validation additions |
| 5.17.1-2 | §9/§17: indeterminate evidence under `Not` never collapses to true — three-valued evaluator, not schema |
| 5.18.1-3 | §4 Gate |
| 5.19.1-3 | §5 Rule, ascending-priority-first-match |
| 5.20.1-3, 5.21.1-3 | §6 `ThresholdDefinition` + §2 `ThresholdRef` |
| 5.22.1-3 | §9 conflict semantics (Gates absorb it) |
| 5.23.1-3 | §14 pipeline ordering, `default_outcome` VERIFIED-prohibition |
| 5.24.1-3 | §14 step 4 rollback; §8 engine codes |
| 5.25.1-4 | §13 pure evaluator — no wall-clock, no I/O, no uncontrolled calls by construction |
| 5.26.1-4 | Existing `MAX_CONDITION_NODES`/`MAX_CONDITION_DEPTH`/`MAX_GATES`/`MAX_RULES`; runtime budget still unimplemented |
| 5.27.1-4 | §12 `DecisionProvenance`, soft references |
| 5.28.1-3 | §7/§8 two-namespace codes |
| 5.29.1-3 | §12 `DecisionResult` |
| 5.30.1-4 | §14 transaction boundary, UNIQUE constraint |
| 5.31.1-3 | Existing `GET /v1/verification-sessions/{id}` tenant-scoped retrieval — DE-004 must make the DecisionResult mapping explicit, not assume the session GET already satisfies it |
| 5.32.1-4 | §14 step 2b; new `AuditEventType.DECISION_PRODUCED`/`DECISION_ENGINE_FAILED` |
| 5.33.1-4 | Free by construction — Policy immutability + `supersedes_id` chain |
| 5.34.1-3 | §6 model-version cross-check → `CALIBRATION_MODEL_MISMATCH`; extended by §17 |
| 5.35.1-4 | This document + §16 |

## 16. Adversarial / property specification

Named properties, each maps to a test:

1. `∀ decision: decision.policy_reference == session(decision).policy_reference` (5.12.2, 5.33.1)
2. `∀ decision: deleting the evidence decision.evidence_references[i] points to does not alter decision` (5.27.2, PRV-11.35.3-4)
3. `∀ session, status ∈ terminal(6): evidence submission → rejected` (WF-4.19.2, DE-004 mandatory gate)
4. `evaluation_reason == EXPIRATION → outcome == INCONCLUSIVE ∧ SESSION_EXPIRED_DURING_PROCESSING ∈ reason_codes`, unconditionally, regardless of what gates/rules would otherwise conclude (WF-4.6)
5. `∀ policy: default_outcome ≠ VERIFIED`, rejected at activation (5.23.1)
6. Two concurrent evaluations of the same session → exactly one `DecisionResult` row, loser observes the winner's (5.30.3, concurrency)
7. Required-audit failure at decision persistence → zero `DecisionResult` rows for that attempt, retry converges (5.32.1, §14 step 4)
8. `EvidenceCondition` referencing a `ThresholdRef` whose evaluated evidence has an incompatible or absent model reference → `CALIBRATION_MODEL_MISMATCH` (5.34.2, extended by §17)
9. `PROHIBITED`-level evidence present, no policy condition references it → does not alter outcome; referenced by a `_present` condition → does (§2/§9)
10. Two non-superseding `EvidenceResult` rows of the same type for one session → constraint violation at write time, or, pre-constraint, deterministic most-recent-wins (§11)
11. `kind=CONFLICT` gate fires with no `failure_reason_code` → `ENGINE:UNRESOLVED_EVIDENCE_CONFLICT`; no gate/rule matches at all → `ENGINE:NO_MATCHING_RULE` — distinguishable in the persisted `reason_codes` (§9)
12. Session creation with no active policy for `(tenant_id, assurance_level)` → session never created, no decision, no `INCONCLUSIVE`
13. Policy code and engine code collision at policy-activation time → `InvalidPolicyError` (§7)

---

## Amendment A — Conditional Gate reason code

Adopted during the DE-003 sign-off review, before any implementation began.

The original §4 left this legal:

```
kind = BLOCKING
on_failure_outcome = REJECTED
failure_reason_code = None
```

which has no legitimate reason code: it cannot use
`ENGINE:UNRESOLVED_EVIDENCE_CONFLICT` (it isn't a conflict gate), and must
not silently manufacture a generic one.

**Fix, frozen**:

```
Gate.failure_reason_code:
    BLOCKING  → required POLICY: code (absence → InvalidPolicyError at activation)
    CONFLICT  → optional POLICY: code, defaults to ENGINE:UNRESOLVED_EVIDENCE_CONFLICT
```

Implemented in `core/policy/gates.py::Gate._reason_code_matches_kind` —
enforced at construction, not at evaluation time, so the ambiguous state is
unconstructable rather than merely discouraged.

## Amendment B — Deterministic duplicate-evidence fallback

Also adopted during the DE-003 sign-off review.

"Most recent by `produced_at` wins" is not fully deterministic if two rows
share a `produced_at` timestamp, which is entirely possible with database
timestamps. **Frozen fix**:

```
ORDER BY produced_at DESC, evidence_result_id DESC
LIMIT 1
```

Principle: every fallback selection must have a total ordering; never rely
on database row order.

Additional implementation requirement adopted in the same amendment: the
defensive fallback must emit an internal observability/audit signal
whenever it is exercised at all (i.e., whenever it finds more than one
candidate) — not merely resolve silently. The primary invariant (the
partial unique index) should make this path unreachable in normal
operation; its occurrence is itself an operational integrity signal worth
surfacing, not a routine case to normalize quietly.

Implemented in `core/evidence_result/effective.py::resolve_one_effective_per_type`
— `max(candidates, key=lambda r: (r.produced_at, r.id))` with a
`logger.warning("duplicate_effective_evidence_detected", ...)` whenever
`len(candidates) > 1`.

---

## §17 — Addendum: Three-valued evaluation and calibration provenance (DE-004 Phase 2)

Adopted during DE-004 Phase 2 implementation and reviewed explicitly before
Phase 3 began. Both items resolve genuine gaps DE-003 left implicit rather
than reinterpreting anything DE-003 stated explicitly.

### 17.1 Condition evaluation is three-valued, not boolean

DE-003 §1-2 defines the condition grammar but not its evaluation semantics
in executable detail — it only inherits DEC-5.17's two requirements:

- **DEC-5.17.1**: indeterminate evidence MUST NOT collapse into boolean
  truth where that could produce unsafe `VERIFIED`.
- **DEC-5.17.2**: policy schema MUST define `INCONCLUSIVE`, unavailable, and
  invalid behavior under negation.

These two requirements are jointly unsatisfiable by a predicate that
returns only `True`/`False`: under two-valued logic, "we could not
determine whether X" must resolve to `False`, and `Not(X)` then resolves to
`True` — precisely the unsafe collapse DEC-5.17.1 forbids.

**Frozen resolution**: `core/decision/condition_eval.py` implements Kleene
three-valued evaluation — `TRUE | FALSE | INDETERMINATE`. Absence, an unset
field, an unresolvable `ThresholdRef`, and an incomparable operand pair all
produce `INDETERMINATE`; `INDETERMINATE` propagates through `Not` unchanged
(never inverts to a determinate value); `AllOf`/`AnyOf` short-circuit on a
decisive `FALSE`/`TRUE` child even when siblings are `INDETERMINATE`, but
otherwise propagate `INDETERMINATE`. Gates and rules match only on `TRUE`,
in both directions — `INDETERMINATE` never fires anything.

This is not a design choice with an alternative; it is the unique minimal
evaluation semantics that satisfies both frozen requirements simultaneously.

### 17.2 Calibrated evaluation without identifiable model provenance

DE-003 §6/§8 (`CALIBRATION_MODEL_MISMATCH`) covers the case of evidence
whose `model_reference` names a model version incompatible with the
threshold's declared `model_id`/`model_version`. It does not explicitly
say what happens when the evidence carries **no** `model_reference` at all
— DEC-5.34.2's wording ("a threshold calibrated for an incompatible model
version MUST NOT be silently reused") describes a comparison between two
named things, and there is nothing named to compare when the field is
absent.

**Frozen resolution**: evidence with no `model_reference`, compared against
a `ThresholdRef`-bound condition, also produces `INCONCLUSIVE` /
`ENGINE:CALIBRATION_MODEL_MISMATCH`.

**Grounding** (not DEC-5.34.2 alone, which is silent on this case, but
DEC-5.34.1 and DEC-5.34.3 read together):

- **DEC-5.34.1** requires that "model changes that can alter decision
  semantics MUST be identifiable in provenance." Evidence with no
  `model_reference` has no identifiable model at all — 5.34.1's
  precondition fails outright, not merely 5.34.2's narrower one.
- **DEC-5.34.3** requires that "historical decisions MUST remain
  attributable to model versions whose evidence they consumed." A decision
  that consumed this evidence against a calibrated threshold would be
  structurally incapable of satisfying 5.34.3 for that evidence — there is
  no model version to attribute it to, ever, no matter what happens later.

So the rule is not "treat missing model reference as a version mismatch by
fiat." It is: **calibrated evaluation without identifiable model provenance
cannot satisfy the frozen provenance invariants (5.34.1, 5.34.3), and must
therefore fail safe** — the same `INCONCLUSIVE` outcome a genuine version
incompatibility produces, for a related but distinct reason.

```text
Calibrated threshold
        +
Evidence without model_reference
        ↓
Cannot establish model provenance (5.34.1)
Cannot ever be attributable (5.34.3)
        ↓
INCONCLUSIVE
ENGINE:CALIBRATION_MODEL_MISMATCH

Calibrated threshold
        +
Evidence with a named, incompatible model_reference
        ↓
Known incompatibility (5.34.2)
        ↓
INCONCLUSIVE
ENGINE:CALIBRATION_MODEL_MISMATCH
```

**No new `ENGINE:` reason code is introduced.** The closed vocabulary (§8)
is not reopened for this case. The two scenarios remain forensically
distinguishable without new vocabulary: `DecisionProvenance.evidence_references`
always lists evidence that participated in evaluation, while
`model_references` lists only evidence that actually carried a
`model_reference`. Evidence appearing in the former but absent from the
latter is, on inspection, exactly the "no provenance asserted" case;
evidence appearing in neither never participated at all.

**Known operational consequence, accepted deliberately**: if a producer
never populates `model_reference` for some evidence type, any policy
gating that type behind a `ThresholdRef` will produce a standing
`INCONCLUSIVE` for that tenant until the producer is fixed. This is treated
as correct fail-safe behavior, not a defect to route around — `INCONCLUSIVE`
with a stable, inspectable reason code is a diagnosable safety outcome
(CLAUDE.md: "`INCONCLUSIVE` is a legitimate safety outcome"), not a silent
one. The alternative — comparing an unattributed score against a calibrated
threshold anyway — is the actual silent failure DEC-5.34.2 forbids by name.

Implemented in `core/decision/evaluator.py::_check_calibration_compatibility`.

**Traceability update**: DEC-5.34.1-3 disposition in §15 now reads "§6
model-version cross-check → `CALIBRATION_MODEL_MISMATCH`; extended by §17,"
and adversarial property 8 in §16 now covers both the named-incompatibility
case and the absent-provenance case under one property.

---

## Status

**DE-003 = FROZEN / APPROVED FOR DE-004 IMPLEMENTATION**, incorporating
Amendments A and B (adopted before implementation began) and the §17
addendum (adopted during Phase 2, reviewed and signed off before Phase 3).

Sections 1–16 are not to be reopened without an explicit architectural
decision of the same weight as amending this document was in the first
place. §17 may itself be extended by a future numbered addendum if a
further gap is found; existing addenda are not retroactively edited.
