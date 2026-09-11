# PaxLI Decision & Verification Semantics Specification

## Part V - Decision Engine

**Semantic Contract:** v1.0  
**Document Status:** Normative  
**Product:** PaxLI by PaxAlpha  
**Positioning:** Identity Verification & Biometric Trust Infrastructure  
**Tagline:** Verify with confidence.

## 5.0 Purpose and Scope

This part defines the normative semantics governing the PaxLI Decision Engine.

The Decision Engine is the authoritative component responsible for transforming an authorized verification evidence set, under a specific immutable verification policy, into a final verification decision. Components produce evidence. Policies define how authorized evidence is interpreted. The Decision Engine alone produces the final verification decision.

This part defines decision authority, outcomes, inputs, evidence requirements, policy representation and validation, normalization, declarative conditions, gates, rules, thresholds, calibration, conflict resolution, precedence, deterministic evaluation, safe failure, complexity limits, provenance, reason codes, persistence, retrieval, auditability, version interaction, and conformance.

It does not define the internal implementation of biometric, liveness, document, OCR, or external-provider components. Those components produce evidence according to Part III.

## 5.1 Decision Engine Definition

**Status: PREREQUISITE: v1.0**

The Decision Engine consumes an authorized verification session context, immutable evidence set, immutable policy version, policy metadata, model references, and evaluation context. It produces exactly one final outcome for a completed decision attempt.

The Decision Engine MUST NOT create evidence as a substitute for missing component output or silently infer evidence that was not produced.

### Requirements

- **DEC-5.1.1** Only the Decision Engine MAY declare a final verification decision.
- **DEC-5.1.2** Intelligence components MUST NOT independently declare `VERIFIED`, `REJECTED`, `REVIEW_REQUIRED`, or `INCONCLUSIVE` as the final decision.
- **DEC-5.1.3** Component results MUST remain evidence and MUST be interpreted according to policy.

## 5.2 Decision Authority

**Status: PREREQUISITE: v1.0**

The authority boundary is:

```text
Component -> Evidence -> Decision Engine -> Final Decision
```

A component may produce `PASS`, `VALID`, or `MATCH`, but none of these results constitutes a final decision.

### Requirements

- **DEC-5.2.1** Component results MUST NOT bypass policy evaluation.
- **DEC-5.2.2** Policy MUST NOT be bypassed because evidence appears sufficiently strong.
- **DEC-5.2.3** A final `VERIFIED` decision MUST be attributable to explicit policy evaluation.

## 5.3 Decision Outcomes

**Status: PREREQUISITE: v1.0**

The final outcome set is:

```text
VERIFIED
REJECTED
REVIEW_REQUIRED
INCONCLUSIVE
```

- **`VERIFIED`** means all applicable policy requirements are satisfied and no blocking condition prevents successful verification.
- **`REJECTED`** means evidence establishes that requirements are not satisfied under a valid deterministic policy evaluation.
- **`REVIEW_REQUIRED`** means authorized human or downstream adjudication is required instead of automatic verification or rejection.
- **`INCONCLUSIVE`** means a valid final decision cannot safely be established from available evidence and execution context.

`INCONCLUSIVE` includes unavailable required evidence, infrastructure or model failure, Decision Engine failure or timeout, unavailable policy version, unresolved conflict, invalid evidence, and processing expiration before valid decision completion.

### Requirements

- **DEC-5.3.1** Every completed decision MUST have exactly one outcome from the defined set.
- **DEC-5.3.2** `INCONCLUSIVE` MUST NOT be interpreted as `REJECTED`.
- **DEC-5.3.3** `REVIEW_REQUIRED` MUST NOT be interpreted as `VERIFIED` or `REJECTED`.

## 5.4 Decision Inputs

**Status: PREREQUISITE: v1.0**

The normative semantic input is:

```text
DecisionInput
|- session_context
|- tenant_context
|- evidence_set
|- policy
|- policy_version
|- model_references
`- evaluation_context
```

### Requirements

- **DEC-5.4.1** The Decision Engine MUST evaluate a specific immutable policy version.
- **DEC-5.4.2** It MUST evaluate only evidence authorized for the tenant and session.
- **DEC-5.4.3** Undeclared or unauthorized evidence MUST NOT influence the decision.
- **DEC-5.4.4** Evaluation context MUST be sufficient to reconstruct why the decision was produced.

## 5.5 Evidence Requirements

**Status: PREREQUISITE: v1.0**

A policy defines evidence that is required, optional, prohibited, or conditionally required. Requirements MAY depend on assurance level or explicitly declared policy conditions.

### Requirements

- **DEC-5.5.1** Required evidence MUST be explicitly represented in policy.
- **DEC-5.5.2** Missing required evidence MUST be distinguishable from evaluated failure.
- **DEC-5.5.3** Missing evidence MUST NOT be treated as successful evidence.

## 5.6 Required vs Optional Evidence

**Status: PREREQUISITE: v1.0**

Required evidence is evidence whose absence prevents successful verification unless an explicit policy rule provides another valid path. Optional evidence MAY contribute but MUST NOT silently become required.

### Requirements

- **DEC-5.6.1** Optional evidence MUST NOT be mandatory unless policy explicitly requires it.
- **DEC-5.6.2** Required evidence that is `NOT_SUBMITTED`, `UNAVAILABLE`, `INCONCLUSIVE`, or unusable MUST follow explicit policy semantics.
- **DEC-5.6.3** Policy MUST NOT convert infrastructure unavailability into evidence failure without explicit semantic basis.

## 5.7 Evidence Evaluation Semantics

**Status: PREREQUISITE: v1.0**

Evidence statuses and decision outcomes remain distinct. `FaceMatch = FAIL` is evidence; `REJECTED` is a decision. `FaceMatch = INCONCLUSIVE` does not itself determine final `INCONCLUSIVE`; policy defines the consequence.

### Requirements

- **DEC-5.7.1** Part III evidence semantics MUST be preserved.
- **DEC-5.7.2** Evidence statuses MUST NOT be reinterpreted inconsistently across evidence types.
- **DEC-5.7.3** A score MUST NOT be interpreted as a probability without calibrated semantics establishing that interpretation.

## 5.8 Policy Definition

**Status: PREREQUISITE: v1.0**

A verification policy is an immutable, versioned declaration of the conditions under which evidence may result in a final decision. Policy is configuration-as-data and MUST NOT contain arbitrary executable application code.

```text
VerificationPolicy
|- policy_id
|- version
|- assurance_level
|- evidence_requirements
|- gates
|- rules
|- thresholds
|- conflict_resolution
`- metadata
```

### Requirements

- **DEC-5.8.1** Policy definitions MUST conform to a versioned schema.
- **DEC-5.8.2** A policy MUST be identifiable independently from its version.
- **DEC-5.8.3** An activated policy version MUST be immutable.
- **DEC-5.8.4** A policy MUST NOT execute arbitrary application code.

## 5.9 Policy Schema

**Status: PREREQUISITE: v1.0**

The schema MUST define allowed fields and types, values, required fields, evidence references, conditions, outcome mappings, thresholds, conflict resolution, complexity limits, and schema version. Unknown or unsupported structures MUST NOT be silently ignored.

### Requirements

- **DEC-5.9.1** Structurally invalid policy fields MUST be rejected before activation.
- **DEC-5.9.2** Unsupported condition types MUST be rejected before activation.
- **DEC-5.9.3** Schema validation MUST occur before a policy becomes executable.

## 5.10 Policy Validation

**Status: PREREQUISITE: v1.0**

Validation MUST include structural schema, semantic, evidence-reference, outcome, threshold, conflict-resolution, and complexity validation.

```text
Policy Definition -> Schema Validation -> Semantic Validation
                  -> Complexity Validation -> Normalization
                  -> Immutable Version -> Executable Policy
```

### Requirements

- **DEC-5.10.1** Invalid policy MUST NOT become active.
- **DEC-5.10.2** Validation failure MUST NOT silently fall back to another policy.
- **DEC-5.10.3** Validation failure MUST produce stable reason codes.

## 5.11 Policy Normalization

**Status: PREREQUISITE: v1.0**

Normalization converts a valid policy into a deterministic canonical representation. It MAY order equivalent structures, normalize identifiers and thresholds, or remove semantically irrelevant representation differences, but MUST NOT change policy meaning.

### Requirements

- **DEC-5.11.1** Equivalent representations MUST normalize to equivalent semantics.
- **DEC-5.11.2** Normalization MUST be deterministic.
- **DEC-5.11.3** The normalized representation MUST support integrity identification such as a canonical hash.

## 5.12 Policy Versioning and Immutability

**Status: PREREQUISITE: v1.0**

Every executable policy has a stable identity and version. Any change to decision semantics MUST produce a new version.

### Requirements

- **DEC-5.12.1** An active policy version MUST NOT be mutated in place.
- **DEC-5.12.2** Historical decisions MUST retain policy identity and version used.
- **DEC-5.12.3** A superseding policy MUST NOT retroactively change historical decisions.
- **DEC-5.12.4** Rollback MUST activate a valid version or create a governed version and MUST NOT rewrite history.

## 5.13 Declarative Condition Model

**Status: PREREQUISITE: v1.0**

Conditions use a constrained declarative model:

```text
Condition
|- EvidenceCondition
|- AllOf
|- AnyOf
`- Not
```

### Requirements

- **DEC-5.13.1** Conditions MUST NOT perform arbitrary database queries.
- **DEC-5.13.2** Conditions MUST NOT perform arbitrary network calls.
- **DEC-5.13.3** Conditions MUST NOT invoke user-defined functions.
- **DEC-5.13.4** Conditions MUST NOT contain unbounded loops or recursion.

## 5.14 `EvidenceCondition`

**Status: PREREQUISITE: v1.0**

`EvidenceCondition` evaluates an explicitly identified evidence property:

```text
EvidenceCondition
|- evidence_type
|- field
|- operator
`- expected_value
```

Examples include `FaceMatch.status == PASS` and `FaceMatch.similarity >= calibrated_threshold`.

### Requirements

- **DEC-5.14.1** An evidence condition MUST reference a defined evidence type and property.
- **DEC-5.14.2** Unsupported properties MUST cause policy validation failure.
- **DEC-5.14.3** Operators MUST be explicitly defined by the policy schema.

## 5.15 `AllOf`

**Status: PREREQUISITE: v1.0**

`AllOf(A, B, C)` is true only when every child is true.

### Requirements

- **DEC-5.15.1** `AllOf` evaluation MUST be deterministic.
- **DEC-5.15.2** Empty `AllOf` semantics MUST be explicit and MUST NOT rely on implementation behavior.

## 5.16 `AnyOf`

**Status: PREREQUISITE: v1.0**

`AnyOf(A, B, C)` is true when at least one child is true.

### Requirements

- **DEC-5.16.1** `AnyOf` MUST NOT treat missing evidence as successful evidence.
- **DEC-5.16.2** Empty `AnyOf` semantics MUST be explicit and MUST NOT rely on implementation behavior.

## 5.17 `Not`

**Status: PREREQUISITE: v1.0**

`Not` reverses the logical result of a valid child condition. It MUST NOT turn unavailable or invalid evidence into positive evidence.

### Requirements

- **DEC-5.17.1** Indeterminate evidence MUST NOT collapse into boolean truth where that could produce unsafe `VERIFIED`.
- **DEC-5.17.2** Policy schema MUST define `INCONCLUSIVE`, unavailable, and invalid behavior under negation.

## 5.18 Gates

**Status: PREREQUISITE: v1.0**

A gate is a condition that MUST be satisfied before a decision path may produce its associated outcome. Blocking gates MAY prevent `VERIFIED` even when other evidence is strong.

### Requirements

- **DEC-5.18.1** Gates MUST be evaluated before dependent decision paths.
- **DEC-5.18.2** A failed blocking gate MUST NOT be overridden by aggregate scores.
- **DEC-5.18.3** Gate semantics MUST be explicit in the active policy.

## 5.19 Rules

**Status: PREREQUISITE: v1.0**

Rules map conditions and evidence states to decision behavior. Rules MUST have deterministic precedence when multiple rules apply.

### Requirements

- **DEC-5.19.1** Rule ordering MUST NOT depend on implementation iteration order.
- **DEC-5.19.2** Conflicting rules MUST be resolved by explicit policy semantics.
- **DEC-5.19.3** Rules MUST NOT produce outcomes outside the defined decision set.

## 5.20 Thresholds

**Status: PREREQUISITE: v1.0**

Thresholds MAY be used for biometric similarity, quality, liveness, document confidence, or calibrated risk metrics. A threshold is a policy parameter, not universal truth; a comparison such as `similarity >= threshold` does not establish identity probability.

### Requirements

- **DEC-5.20.1** Thresholds MUST be associated with applicable evidence and model semantics.
- **DEC-5.20.2** Thresholds MUST NOT be silently reused across incompatible models.
- **DEC-5.20.3** Ungoverned hard-coded production thresholds MUST NOT determine final decisions.

## 5.21 Calibration Semantics

**Status: PREREQUISITE: v1.0**

A similarity score is not automatically a probability, identity confidence percentage, fraud probability, or calibrated risk value. A probabilistic interpretation requires documented calibration.

### Requirements

- **DEC-5.21.1** Uncalibrated scores MUST NOT be described as probabilities.
- **DEC-5.21.2** Calibration metadata MUST be versioned when it affects decisions.
- **DEC-5.21.3** Thresholds MUST identify the model and calibration context for which they were established.

## 5.22 Conflict Resolution

**Status: PREREQUISITE: v1.0**

Conflicting evidence, such as `FaceMatch = PASS` with `IdentityProvider = MISMATCH`, MUST be resolved by policy rather than arbitrary implementation precedence.

### Requirements

- **DEC-5.22.1** Conflicts MUST NOT be resolved through arbitrary precedence.
- **DEC-5.22.2** A policy-defined blocking conflict MUST prevent `VERIFIED`.
- **DEC-5.22.3** A material conflict that policy cannot safely resolve MUST produce `INCONCLUSIVE`. `REVIEW_REQUIRED` is permitted only when the active policy explicitly defines the conflict as a human or downstream adjudication condition.

## 5.23 Decision Precedence

**Status: PREREQUISITE: v1.0**

PaxLI prioritizes safety over optimistic verification:

```text
Invalid Decision Context -> Safe Failure
Blocking Evidence/Gate -> Policy-defined non-VERIFIED path
Required Evidence Satisfied -> Rule Evaluation
Successful Policy Evaluation -> VERIFIED
```

### Requirements

- **DEC-5.23.1** No optimistic fallback to `VERIFIED` is permitted when required evidence or policy evaluation is unresolved.
- **DEC-5.23.2** Infrastructure failure MUST NOT become `REJECTED` merely because processing could not complete.
- **DEC-5.23.3** Precedence MUST be deterministic.

## 5.24 Safe Decision Failure

**Status: PREREQUISITE: v1.0**

If the Decision Engine cannot produce a valid deterministic decision from a valid policy and evaluation context, it MUST NOT produce `VERIFIED`. It MUST also avoid `REJECTED` when the cause is infrastructure or execution failure rather than evidence establishing rejection. The safe fallback is `INCONCLUSIVE`.

### Requirements

- **DEC-5.24.1** Decision Engine exceptions MUST NOT result in implicit `VERIFIED`.
- **DEC-5.24.2** Decision Engine infrastructure failure MUST NOT result in implicit `REJECTED`.
- **DEC-5.24.3** Safe failure MUST produce a stable reason code, including applicable codes such as `DECISION_ENGINE_ERROR`, `POLICY_INVALID`, `POLICY_NOT_FOUND`, `POLICY_VERSION_UNAVAILABLE`, `EVIDENCE_CONFLICT`, `REQUIRED_EVIDENCE_MISSING`, `EVIDENCE_SCHEMA_INVALID`, and `DECISION_TIMEOUT`.

## 5.25 Decision Determinism

**Status: PREREQUISITE: v1.0**

For identical session context, authorized evidence set, policy version, model references, calibration references, and decision configuration, the Decision Engine MUST produce the same outcome.

### Requirements

- **DEC-5.25.1** Evaluation MUST NOT depend on wall-clock time unless time is explicit policy input.
- **DEC-5.25.2** Evaluation MUST NOT depend on nondeterministic iteration order.
- **DEC-5.25.3** Evaluation MUST NOT make uncontrolled external calls.
- **DEC-5.25.4** Randomness MUST NOT influence a final decision unless governed, reproducible, and represented in provenance.

## 5.26 Decision Timeout and Complexity Limits

**Status: PREREQUISITE: v1.0**

Policies MUST have bounded complexity. Limits include maximum gates, rules, conditions, nesting depth, expression size, and evaluation time. Exact limits MUST be selected through benchmarking and documented as governed configuration.

### Requirements

- **DEC-5.26.1** Policies exceeding complexity limits MUST NOT activate.
- **DEC-5.26.2** Evaluation exceeding its runtime budget MUST terminate safely.
- **DEC-5.26.3** Decision timeout MUST produce `INCONCLUSIVE`, not `VERIFIED`.
- **DEC-5.26.4** Runtime complexity MUST NOT justify bypassing policy evaluation.

## 5.27 Decision Provenance

**Status: PREREQUISITE: v1.0**

Every final decision MUST contain sufficient provenance:

```text
DecisionProvenance
|- decision_id
|- session_id
|- tenant_id
|- policy_id
|- policy_version
|- policy_hash
|- evidence_references
|- model_references
|- calibration_references
|- reason_codes
|- evaluated_at
`- engine_version
```

### Requirements

- **DEC-5.27.1** Provenance MUST reference the policy version.
- **DEC-5.27.2** Provenance MUST reference evidence used.
- **DEC-5.27.3** Provenance MUST identify relevant model and calibration versions.
- **DEC-5.27.4** Provenance MUST NOT contain raw credentials or unrestricted sensitive payloads.

## 5.28 Decision Reason Codes

**Status: PREREQUISITE: v1.0**

Final decisions MUST include stable machine-readable reason codes. Codes MUST distinguish evidence-derived rejection, review conditions, missing evidence, infrastructure failure, and Decision Engine failure. Examples include `VERIFIED_POLICY_SATISFIED`, `REQUIRED_EVIDENCE_MISSING`, `LIVENESS_FAILED`, `FACE_MATCH_FAILED`, `DOCUMENT_INVALID`, `IDENTITY_MISMATCH`, `EVIDENCE_CONFLICT`, `REVIEW_POLICY_TRIGGERED`, `EXTERNAL_PROVIDER_UNAVAILABLE`, `DECISION_ENGINE_ERROR`, and `DECISION_TIMEOUT`.

### Requirements

- **DEC-5.28.1** A reason code MUST NOT falsely describe infrastructure failure as evidence failure.
- **DEC-5.28.2** Reason codes MUST NOT contain secrets or raw biometric/document data.
- **DEC-5.28.3** Reason-code semantics MUST remain stable within a major API contract unless versioned.

## 5.29 Decision Result Object

**Status: PREREQUISITE: v1.0**

A decision result contains sufficient information for authorized clients and internal systems without exposing implementation details.

```text
DecisionResult
|- decision_id
|- session_id
|- outcome
|- reason_codes
|- policy_reference
|- created_at
`- provenance_reference
```

### Requirements

- **DEC-5.29.1** Public results MUST expose the final outcome.
- **DEC-5.29.2** Public results MUST expose stable reason codes appropriate to caller authorization.
- **DEC-5.29.3** Worker state, stack traces, infrastructure topology, and secrets MUST NOT be exposed in decision results.

## 5.30 Decision Persistence

**Status: PREREQUISITE: v1.0**

A final decision MUST be durably persisted before it is externally completed. Persisted results MUST prevent ambiguity between successive or contradictory attempts.

### Requirements

- **DEC-5.30.1** A committed decision MUST remain retrievable according to retention policy.
- **DEC-5.30.2** Webhook delivery MUST NOT determine whether a decision is persisted.
- **DEC-5.30.3** A crash after persistence MUST NOT create a contradictory replacement.
- **DEC-5.30.4** Historical decisions MUST NOT be silently overwritten.

## 5.31 Decision Retrieval

**Status: PREREQUISITE: v1.0**

Authorized clients MUST retrieve final decisions through the verification-session API defined by Parts IV and VI. Retrieval respects tenant boundaries, authorization, retention, immutability, and API visibility rules.

### Requirements

- **DEC-5.31.1** Authorized tenants MUST NOT require webhook delivery to retrieve a persisted decision.
- **DEC-5.31.2** Unauthorized tenants MUST NOT retrieve another tenant's decision.
- **DEC-5.31.3** Retrieval MUST NOT mutate the historical decision.

## 5.32 Decision Auditability

**Status: PREREQUISITE: v1.0**

Every final decision MUST be auditable. The record MUST permit reconstruction of actor, tenant, session, evidence, policy, model/calibration references, evaluation, and outcome. System-generated decisions MUST use an appropriate `SYSTEM` authorization context.

### Requirements

- **DEC-5.32.1** Decision creation MUST generate the required durable audit event.
- **DEC-5.32.2** Policy changes affecting future decisions MUST generate required policy audit events.
- **DEC-5.32.3** Audit records MUST NOT contain raw credentials, tokens, or unnecessary biometric/document content.
- **DEC-5.32.4** Decision audit ordering MUST preserve durable decision creation before externally observable notification.

## 5.33 Policy Change Interaction

**Status: PREREQUISITE: v1.0**

Changing policy creates a new decision environment. A new policy MUST NOT mutate historical decisions.

### Requirements

- **DEC-5.33.1** Historical decisions MUST retain their original policy version.
- **DEC-5.33.2** Policy updates MUST NOT retroactively alter persisted outcomes.
- **DEC-5.33.3** Policy activation MUST be auditable.
- **DEC-5.33.4** Rollback MUST preserve historical provenance.

## 5.34 Model Version Interaction

**Status: PREREQUISITE: v1.0**

Model identity and version are part of decision provenance when model output affects the decision.

### Requirements

- **DEC-5.34.1** Model changes that can alter decision semantics MUST be identifiable in provenance.
- **DEC-5.34.2** A threshold calibrated for an incompatible model version MUST NOT be silently reused.
- **DEC-5.34.3** Historical decisions MUST remain attributable to model versions whose evidence they consumed.

## 5.35 Conformance Requirements

**Status: PREREQUISITE: v1.0**

Conformance MUST be organized around normative `DEC-*` requirements and cover authority, outcomes, evidence requirements, validation, immutability, conditions, gates, rules, thresholds, calibration, conflicts, determinism, safe failure, complexity, provenance, reason codes, persistence, retrieval, auditability, and policy/model version interaction.

Suggested contract structure:

```text
tests/contracts/decision/
|- test_authority.py
|- test_outcomes.py
|- test_evidence_requirements.py
|- test_policy_validation.py
|- test_conditions.py
|- test_gates.py
|- test_rules.py
|- test_thresholds.py
|- test_conflicts.py
|- test_determinism.py
|- test_safe_failure.py
|- test_provenance.py
|- test_persistence.py
`- test_auditability.py
```

### Requirements

- **DEC-5.35.1** Every normative requirement MUST have at least one conformance assertion before the capability is contract-complete.
- **DEC-5.35.2** Reports MUST identify the specific normative requirement satisfied or violated.
- **DEC-5.35.3** Passing a higher-level suite alone MUST NOT establish conformance.
- **DEC-5.35.4** Adversarial policy, malformed evidence, contradictory evidence, invalid thresholds, unavailable dependencies, and Decision Engine failures MUST be tested.

## 5.36 Deferred Decision Capabilities

**Status: FUTURE unless separately adopted through governed specification change**

The following are deferred: advanced policy simulation, A/B testing, shadow evaluation, generative-AI explanations, adaptive thresholding, automated policy optimization, multi-policy ensembles, advanced human-review orchestration, decision-risk scoring beyond calibrated evidence, and cross-tenant decision intelligence.

Deferred capabilities MUST NOT be introduced implicitly through implementation convenience.

## 5.37 Normative Decision Model

```text
Authorized Verification Session
            |
      Immutable Evidence
            |
     Immutable Policy
            |
     Policy Validation
            |
   Evidence/Context Validation
            |
      Gate Evaluation
            |
       Rule Evaluation
            |
     Conflict Resolution
            |
   Deterministic Outcome
       |       |       |
  VERIFIED REJECTED REVIEW_REQUIRED
            |
       INCONCLUSIVE on safe failure
            |
    Durable Decision Result
            |
       Required Audit
            |
      Client Notification
```

The final outcome MUST be produced only after applicable policy validation and evaluation succeed, or after a governed safe-failure path produces `INCONCLUSIVE`.

## 5.38 Constitutional Principle

> **Evidence describes what the system observed. Policy defines how authorized evidence is interpreted. The Decision Engine determines the final outcome.**

Models produce evidence, not verdicts. Scores retain their actual semantics. Policies are explicit and versioned. Decisions are deterministic. Conflicts are governed. Failures are safe. Historical decisions are reconstructible. No implementation convenience may override Decision Engine authority.

PaxLI MUST never claim verification merely because the system was unable to establish that verification was false. PaxLI calls a verification successful only when the Decision Engine produces a valid `VERIFIED` decision under an authorized policy and that decision is durably recorded.
