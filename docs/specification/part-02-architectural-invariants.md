# Averiq by PaxAlpha

# Decision & Verification Semantics Specification

## Part II - Architectural Invariants

**Document Status:** Normative  
**Specification Version:** Semantic Contract v1.0  
**Product:** Averiq by PaxAlpha  
**Positioning:** Identity Verification & Biometric Trust Infrastructure  
**Tagline:** Verify with confidence.

## 2.0 Purpose

This part defines the architectural invariants that govern the behavior, implementation, testing, and release of Averiq v1.0.

These invariants are normative constraints. An implementation is conformant with Semantic Contract v1.0 only when it satisfies all applicable requirements defined by these invariants and their associated contract tests. Where an implementation conflicts with an invariant, the invariant takes precedence. The implementation MUST NOT silently redefine the semantics specification. Changes to an invariant, its meaning, or its normative requirements MUST follow the specification governance process defined in Part I.

## 2.1 Normative Language

- **MUST** indicates an absolute requirement.
- **MUST NOT** indicates an absolute prohibition.
- **SHOULD** indicates a strong recommendation; deviation requires documented technical justification where appropriate.
- **SHOULD NOT** indicates discouraged behavior unless documented justification exists.
- **MAY** indicates an explicitly permitted implementation choice.
- **MUST NOT silently** means behavior MUST NOT be introduced as an implementation detail when it alters an established semantic contract.

## 2.2 Scope Classification

Unless explicitly marked otherwise, every invariant is a v1.0 prerequisite. Deferred capabilities are not v1.0 release blockers unless promoted through specification governance. Deferred architecture is governed by Part IX.

The following capabilities are deferred from v1.0:

- advanced liveness and presentation-attack detection implementation;
- NIMC integration;
- BVN integration;
- 1:N biometric identification;
- cross-tenant biometric search;
- advanced fraud intelligence;
- advanced biometric capabilities.

Deferred capabilities MUST NOT introduce semantics that conflict with these v1.0 invariants.

## 2.3 Invariant Dependency and Reading Order

The stable invariant numbers are not renumbered when implementation or specification structure changes. The semantic dependency order is:

```text
03 Explicit Evidence Semantics
        |
06 Evidence Integrity
        |
01 Verdict Authority
        |
02 Safe Decision Failure
        |
07 Policy Immutability
        |
04 Durable Results
        |
05 Webhook Independence
        |
11 Result Accessibility
        |
08 Tenant Isolation
        |
09 Credential Separation
        |
10 Bounded Policy Evaluation
        |
12 Audit Completeness
```

Cross-references MUST be used whenever an invariant relies on terminology formally defined elsewhere.

## 2.4 Invariant 01 - Verdict Authority

**Status: PREREQUISITE: v1.0**

### Normative statement

No component outside the Decision Engine may declare a final verification verdict. The Decision Engine is the sole authority capable of producing a final verification outcome.

The v1.0 final outcomes are `VERIFIED`, `REJECTED`, `REVIEW_REQUIRED`, and `INCONCLUSIVE`. Intelligence components MUST produce evidence or component-level outcomes rather than final verification verdicts. This includes face matching, document analysis, OCR, document authenticity, identity consistency, future liveness/PAD, and external identity providers.

### Requirements

- **1.1** Only the Decision Engine MUST be authorized to produce final verification outcomes.
- **1.2** Intelligence components MUST expose component-level results rather than final verification verdicts.
- **1.3** Component results MUST NOT be implicitly treated as final verdicts by API, persistence, orchestration, or webhook layers.
- **1.4** The API MUST obtain the final outcome from the Decision Engine result.
- **1.5** Webhook payloads MUST represent the persisted verification result and MUST NOT independently calculate a verdict.
- **1.6** Persistence layers MUST NOT override the Decision Engine outcome.
- **1.7** Administrative interfaces MUST NOT directly change a verification verdict outside the governed decision process.
- **1.8** Policy configuration MUST influence decisioning only through the Decision Engine.

### Detection and response

Contract tests, type/interface restrictions, service-boundary tests, integration tests, and static analysis SHOULD detect violations. A detected violation blocks semantic conformance until the unauthorized authority is removed or the specification is formally amended.

The contract suite MUST prove that components cannot produce final verdicts, the Decision Engine is the sole authority, API responses derive outcomes from it, and webhook processing cannot alter or calculate the result.

**Legitimate exceptions:** None for v1.0.

## 2.5 Invariant 02 - Safe Decision Failure

**Status: PREREQUISITE: v1.0**

If the Decision Engine cannot produce a valid deterministic decision from a valid policy and evidence set, it MUST NOT produce `VERIFIED` or `REJECTED`; it MUST produce `INCONCLUSIVE`.

### Requirements

- **2.1** Decision Engine execution failure MUST result in `INCONCLUSIVE`.
- **2.2** Policy retrieval failure MUST NOT produce `VERIFIED` or `REJECTED`.
- **2.3** Required evidence missing from a decision MUST NOT produce `VERIFIED`.
- **2.4** Invalid evidence semantics MUST NOT produce `VERIFIED`.
- **2.5** Unresolved conflicting evidence MUST result in `INCONCLUSIVE`.
- **2.6** Decision timeout MUST result in `INCONCLUSIVE`.
- **2.7** Invalid or unavailable policy versions MUST result in `INCONCLUSIVE`.
- **2.8** Required-evidence dependency outages MUST NOT be interpreted as identity fraud.
- **2.9** Infrastructure failures MUST use appropriate reason codes, including `DECISION_ENGINE_ERROR`, `POLICY_INVALID`, `POLICY_NOT_FOUND`, `POLICY_VERSION_UNAVAILABLE`, `EVIDENCE_CONFLICT`, `REQUIRED_EVIDENCE_MISSING`, `EVIDENCE_SCHEMA_INVALID`, and `DECISION_TIMEOUT`.

The system MUST prevent unsafe verdicts, produce `INCONCLUSIVE`, record a reason code and audit information, expose the result according to API semantics, and permit recovery or retry where applicable. Contract tests MUST inject policy failure, evidence failure, timeout, dependency outage, malformed evidence, conflicting evidence, and missing required evidence, proving that `VERIFIED` and `REJECTED` are impossible outcomes.

**Legitimate exceptions:** None for safety failures.

## 2.6 Invariant 03 - Explicit Evidence Semantics

**Status: PREREQUISITE: v1.0**

Evidence absence, non-requirement, failure, unavailability, and inconclusiveness are distinct semantic states and MUST NOT be implicitly conflated. The closed evidence vocabulary includes `PASS`, `FAIL`, `INCONCLUSIVE`, `NOT_REQUIRED`, `NOT_SUBMITTED`, `UNAVAILABLE`, and `NOT_RUN` as defined by Part III.

### Requirements

- **3.1** Every evidence component MUST expose an explicitly defined status.
- **3.2** Evidence statuses MUST come from a closed vocabulary.
- **3.3** Unknown, undefined, invalid, or missing statuses MUST NOT be accepted.
- **3.4** Invalid or missing status MUST produce `EVIDENCE_SCHEMA_INVALID`.
- **3.5** Schema violations MUST prevent unsafe approval and map to `INCONCLUSIVE` at decision level.
- **3.6** `NOT_REQUIRED` MUST explicitly indicate that the active policy does not require the evidence.
- **3.7** `NOT_SUBMITTED` MUST indicate required evidence was not provided.
- **3.8** `UNAVAILABLE` MUST indicate evidence could not be obtained or accessed because of an availability condition.
- **3.9** `INCONCLUSIVE` MUST indicate that a trustworthy pass or fail could not be established.
- **3.10** `FAIL` MUST represent an actual component-level negative finding.
- **3.11** Infrastructure failure MUST NOT silently become `FAIL`.
- **3.12** Low confidence MUST NOT silently become an attack or fraud determination without an explicit semantic rule.

Validation, normalization, Decision Engine input validation, and contract tests MUST detect violations. Tests MUST prove that unknown and missing statuses are rejected, `NOT_REQUIRED` differs from `NOT_SUBMITTED`, `UNAVAILABLE` differs from `FAIL`, `INCONCLUSIVE` differs from `FAIL`, and infrastructure failures cannot become component failures without an explicit rule.

**Legitimate exceptions:** None for evidence-state ambiguity.

## 2.7 Invariant 04 - Durable Results

**Status: PREREQUISITE: v1.0**

A verification result MUST be durably persisted before webhook delivery is attempted.

### Requirements

- **4.1** The final result MUST be durably persisted before the first webhook delivery attempt.
- **4.2** The persisted result MUST contain sufficient provenance to reconstruct decision context.
- **4.3** Webhook attempts MUST reference the persisted result rather than create a new result.
- **4.4** An authorized client MUST be able to retrieve the persisted result through the verification-session API.
- **4.5** Webhook failure MUST NOT roll back the committed result.
- **4.6** Persistence failure MUST prevent the system from claiming durable completion.

The required ordering is `Decision -> Durable Result -> Webhook Attempt`. Contract tests MUST fail if webhook delivery occurs before durable result persistence.

**Legitimate exceptions:** None for result/webhook ordering.

## 2.8 Invariant 05 - Webhook Independence

**Status: PREREQUISITE: v1.0**

Webhook delivery failure MUST never alter the underlying verification result. Webhooks are notification mechanisms, not decision mechanisms.

### Requirements

- **5.1** Webhook delivery MUST operate independently of decisioning.
- **5.2** Webhook failure MUST NOT modify the verification outcome.
- **5.3** Retries MUST reference the same durable event/result.
- **5.4** Webhook events MUST have durable identifiers.
- **5.5** Payloads MUST include an explicit payload version.
- **5.6** Delivery state MUST be tracked separately from verification state.
- **5.7** Retry behavior MUST use bounded retry policies.
- **5.8** Dead-lettered events MUST remain distinguishable from failed verifications.
- **5.9** Clients SHOULD process events idempotently.
- **5.10** Polling MUST remain available as an independent recovery mechanism.

Tests MUST simulate HTTP 500, timeout, DNS/network failure, repeated failure, duplicate delivery, and delayed delivery. The persisted result MUST remain unchanged.

**Legitimate exceptions:** None for verification-result independence.

## 2.9 Invariant 06 - Evidence Integrity

**Status: PREREQUISITE: v1.0**

Evidence MUST be immutable during its authorized lifecycle and MUST be integrity-verifiable. Immutability does not imply indefinite retention; authorized deletion is a distinct lifecycle operation.

### Requirements

- **6.1** Immutable evidence content MUST NOT be modified in place.
- **6.2** Evidence integrity MUST be verifiable.
- **6.3** Evidence metadata MUST identify the evidence object and session.
- **6.4** Evidence MUST remain tenant-scoped.
- **6.5** Integrity verification MUST detect unauthorized content modification.
- **6.6** Repositories SHOULD avoid arbitrary update operations for immutable evidence.
- **6.7** Stored evidence SHOULD maintain content checksums.
- **6.8** Deletion MUST be an explicit authorized lifecycle operation.
- **6.9** Authorized deletion MUST produce the audit event required by Invariant 12.
- **6.10** Deletion MUST NOT be interpreted as historical content modification.
- **6.11** Deleted sensitive content MUST NOT be retained merely because it appeared in audit metadata.

Unauthorized mutation is an integrity violation. Affected evidence MUST NOT be treated as trustworthy until integrity is established. Contract tests MUST cover immutability, checksum mismatch, tenant boundaries, authorized deletion, deletion audit, and absence of deleted content from audit records.

**Legitimate exceptions:** Authorized evidence deletion is a lifecycle operation, not an exception to immutability. Other exceptions require explicit approval and registration.

## 2.10 Invariant 07 - Policy Immutability

**Status: PREREQUISITE: v1.0**

An activated policy version MUST NOT be mutated. Changes MUST produce a new policy version.

### Requirements

- **7.1** Every activated policy MUST have an immutable version identifier.
- **7.2** An activated version MUST NOT be modified in place.
- **7.3** A policy change MUST create a new version.
- **7.4** The active version used for a verification MUST be recorded with the decision.
- **7.5** The decisioning representation MUST be reproducible.
- **7.6** Policy identity and version MUST be auditable.
- **7.7** Policy configuration MUST be validated before activation.
- **7.8** Invalid policies MUST NOT become active.
- **7.9** Rollback MUST activate a previously valid version rather than mutate history.
- **7.10** Historical records MUST retain their original policy version.

Policy mutation MUST be rejected. Unauthorized mutation compromises provenance and MUST be audited. Tests MUST demonstrate immutability, new-version creation, historical references, safe rollback, and invalid-policy rejection.

**Legitimate exceptions:** None for mutation of an activated version.

## 2.11 Invariant 08 - Tenant Isolation

**Status: PREREQUISITE: v1.0**

A tenant MUST be able to access only resources within its authorized security boundary.

### Requirements

- **8.1** `tenant_id` MUST be mandatory on all tenant-owned resources.
- **8.2** Resource lookup MUST be tenant-scoped before data is returned.
- **8.3** Tenant identity MUST derive from authenticated security context, not an untrusted client identifier.
- **8.4** A client MUST NOT switch tenant context by modifying a request field or header.
- **8.5** Verification sessions MUST be tenant-scoped.
- **8.6** Evidence MUST be tenant-scoped.
- **8.7** Policies MUST be tenant-scoped.
- **8.8** Tenant-owned audit events MUST be tenant-scoped.
- **8.9** Credentials MUST be associated with their authorized tenant.
- **8.10** Cross-tenant resource references MUST be rejected unless explicitly authorized by a future capability.
- **8.11** Cross-tenant existence MUST NOT be disclosed through errors.
- **8.12** Cross-tenant biometric search MUST NOT exist implicitly through shared vector infrastructure.
- **8.13** Administrative resources MUST be tenant-isolated.
- **8.14** Repository and service authorization boundaries MUST enforce isolation, not merely client behavior.

Cross-tenant attempts MUST be denied without disclosing protected information. Appropriate security audit signals MAY be produced without exposing sensitive information. Contract tests MUST use at least two tenants and cover every requirement above, including session, evidence, policy, audit, credential, management, repository, service, storage, and search boundaries.

**Legitimate exceptions:** No implicit cross-tenant access is permitted in v1.0. Any future capability must be specified, authorized, audited, and isolated from the default model.

## 2.12 Invariant 09 - Credential Separation

**Status: PREREQUISITE: v1.0**

Operational credentials MUST NOT be capable of exercising administrative governance capabilities.

### Requirements

- **9.1** Operational credentials MUST be limited to explicitly authorized verification operations.
- **9.2** Administrative credentials MUST be separately authorized.
- **9.3** Operational credentials MUST NOT manage policies.
- **9.4** Operational credentials MUST NOT create, rotate, or revoke credentials.
- **9.5** Operational credentials MUST NOT modify webhook configuration.
- **9.6** Operational credentials MUST NOT administer tenant configuration.
- **9.7** Administrative operations MUST require appropriate administrative permissions.
- **9.8** Credential issuance, rotation, and revocation MUST be auditable.
- **9.9** Credential secrets MUST NOT appear in audit events, logs, errors, or responses beyond authorized one-time issuance.
- **9.10** Revocation MUST take effect without requiring the compromised credential to cooperate.
- **9.11** Operational and administrative credentials SHOULD be separable at API and authorization boundaries.

Unauthorized administrative access MUST be denied without partial execution and SHOULD produce an appropriate security audit signal. Tests MUST prove the permitted and denied operations for operational and administrative credentials.

**Legitimate exceptions:** None for privilege separation.

## 2.13 Invariant 10 - Bounded Policy Evaluation

**Status: PREREQUISITE: v1.0**

Every executable verification policy MUST have a finite and enforceable complexity bound. Policies use a constrained declarative representation and MUST NOT become an unrestricted programming environment.

### Requirements

- **10.1** Policies MUST conform to a strict schema.
- **10.2** Policies MUST use only the supported declarative condition model.
- **10.3** The v1.0 condition model is finite and explicitly defined, including `EvidenceCondition`, `AllOf`, `AnyOf`, and `Not`.
- **10.4** Policies MUST NOT contain arbitrary executable code.
- **10.5** Policies MUST NOT make arbitrary network calls.
- **10.6** Policies MUST NOT make arbitrary database queries.
- **10.7** Policies MUST NOT define user-supplied functions.
- **10.8** Policies MUST be semantically validated before activation.
- **10.9** Policies MUST be complexity-validated before activation.
- **10.10** Complexity ceilings MUST include maximum gates, conditions per policy, conditions per gate, nesting depth, serialized expression size, and evaluation time. Exact numerical limits are benchmark-derived TBD values and MUST be established before production release.
- **10.11** Runtime evaluation MUST enforce an execution budget.
- **10.12** A budget-exceeding policy MUST NOT produce `VERIFIED` or `REJECTED`.
- **10.13** Validation MUST occur before activation, not only during execution.
- **10.14** A policy rejected for complexity MUST NOT become active.

The three defense layers are schema validation, semantic/complexity validation, and runtime execution budget. Failure at any layer MUST prevent unsafe execution. Policy-time violations reject activation; runtime violations terminate safely with `INCONCLUSIVE` and `DECISION_TIMEOUT` or another deterministic Decision Engine failure reason. Contract tests MUST cover all three layers.

**Legitimate exceptions:** No arbitrary-code or unbounded-policy exception is permitted.

## 2.14 Invariant 11 - Result Accessibility

**Status: PREREQUISITE: v1.0**

Once a verification result is durably committed, webhook delivery status MUST never prevent the authorized tenant from retrieving that result through the verification-session API.

### Requirements

- **11.1** Every durably committed result MUST be retrievable through the authorized API.
- **11.2** Webhook state MUST NOT determine API result availability.
- **11.3** Webhook failure MUST NOT make a retrievable result unavailable.
- **11.4** Retries MUST NOT create an alternative result.
- **11.5** The API MUST return the authoritative persisted result.
- **11.6** Retrieval MUST enforce tenant authorization.
- **11.7** Retrieval MUST expose only contract-authorized information.
- **11.8** Clients MUST NOT need a successful webhook before retrieving a result.

Contract tests MUST commit a result, force repeated webhook failure and dead-lettering, retrieve through the API, and verify the same authoritative result remains accessible.

**Legitimate exceptions:** Temporary platform outage is not a semantic exception if the result remains durably persisted and becomes retrievable after service recovery.

## 2.15 Invariant 12 - Audit Completeness

**Status: PREREQUISITE: v1.0**

Every verification-relevant, governance-relevant, and authorization-relevant action MUST produce a durable, integrity-protected audit event before that action's effects are observable externally. No audit event may be written after the fact.

### Requirements

- **12.1** Every verification-relevant action MUST produce an audit event where defined by the taxonomy.
- **12.2** Governance actions MUST be audited, including policy lifecycle, credential lifecycle, webhook configuration, and tenant configuration changes.
- **12.3** Authorization-relevant actions MUST be audited where defined, including privileged success, rejection, credential lifecycle, and security-boundary violations.
- **12.4** System-initiated actions MUST be auditable, including expiry, retention deletion, automated retry, scheduled processing, and lifecycle transitions.
- **12.5** System events MUST use actor type `SYSTEM`.
- **12.6** System actions MUST NOT use a null actor merely because no human initiated them.
- **12.7** Applicable audit events MUST contain a typed `AuthorizationContext`.
- **12.8** Audit events MUST be durably persisted according to required durability before the external effect.
- **12.9** Audit events MUST be integrity-protected.
- **12.10** Audit records MUST NOT contain raw credentials, tokens, private keys, biometric data, or unnecessarily sensitive payloads.
- **12.11** Audit sanitization MUST NOT silently fail.
- **12.12** Required audit persistence failures MUST NOT be silently swallowed.
- **12.13** The system MUST define transaction-critical and best-effort audit events.
- **12.14** Transaction-critical audit MUST be durable before the associated effect is observable.
- **12.15** Audit events MUST have stable identifiers.
- **12.16** Audit events MUST include sufficient correlation information.
- **12.17** Tenant-owned audit records MUST remain tenant-scoped.
- **12.18** Authorized evidence deletion MUST generate an audit event.
- **12.19** Audit records MUST NOT recreate deleted biometric or document content.

### Authorization context

`AuthorizationContext` is a typed object rather than an arbitrary string. Its conceptual v1.0 structure is:

```text
AuthorizationContext
|- actor_type
|- actor_id
|- tenant_id
|- credential_id
|- authentication_method
|- permission_used
|- request_id
|- source
`- timestamp
```

Valid actor categories include at minimum `HUMAN_OPERATOR`, `SERVICE`, and `SYSTEM`.

### Ordering and response

The normative ordering is:

```text
Action -> Required Audit Event -> Observable Effect
```

The reverse ordering is prohibited. For required events, the effect MUST NOT proceed until audit persistence succeeds. If persistence fails, the action MUST fail safely and no false confirmation may be returned. Best-effort events MUST follow explicitly defined semantics and MUST NOT be represented as guaranteed durable audit.

The audit contract suite MUST cover verification creation and decision, evidence submission and deletion, session expiration and cancellation, policy lifecycle, credential lifecycle, authorization failures, and system actions.

**Legitimate exceptions:** Only explicitly defined best-effort events or numbered approved exceptions.

## 2.16 Invariant Violation Taxonomy

Every violation MUST be classified as one of:

### Policy validation failure
A policy submission or activation violates schema, semantic, or complexity constraints. The policy MUST be rejected and MUST NOT become active. This is not a verification failure.

### Runtime safety failure
The system cannot safely execute an otherwise valid operation, such as dependency outage, Decision Engine timeout, storage failure, provider timeout, or required audit persistence failure. Verification decisioning generally becomes `INCONCLUSIVE`, not `REJECTED`.

### Architectural conformance violation
The implementation violates an architectural invariant, such as unauthorized verdict authority, policy mutation, privilege escalation, webhook result mutation, cross-tenant access, or observable effects before required audit persistence. Conformance MUST be considered failed and the violation MUST be corrected before release conformance.

## 2.17 Invariant Violation Record

Each detected violation SHOULD capture the following without unnecessary sensitive information:

```text
InvariantViolation
|- invariant_id
|- requirement_id
|- violation_type
|- description
|- detection_point
|- affected_component
|- affected_resource
|- detected_at
|- severity
|- required_response
|- resolution_status
`- exception_reference
```

## 2.18 Legitimate Exception Governance

Exceptions are architectural decisions, not informal developer permissions. Every exception MUST:

1. have a unique identifier;
2. identify the affected invariant and requirement;
3. document the exact excepted behavior;
4. provide architectural justification;
5. document security, reliability, and trust implications;
6. identify affected components;
7. identify affected contract tests;
8. define compensating controls where applicable;
9. receive architect approval;
10. be entered into the Approved Exception Registry;
11. have an explicit status and review condition.

No undocumented exception is legitimate. An alleged exception found only in source code, a pull request, local documentation, an unapproved issue, or verbal agreement MUST be treated as no exception.

## 2.19 Invariant Conformance Reporting

Conformance MUST be reported at normative-requirement level, not merely invariant level. Every requirement has a stable identifier and MUST report status, failure reason, and release impact.

Example:

```text
Invariant 08 - Tenant Isolation
8.1  tenant_id mandatory                  PASS
8.2  tenant-scoped lookup                 PASS
8.3  tenant derived from auth context     PASS
8.4  client tenant switching prevented    PASS
8.5  session isolation                    PASS
8.6  evidence isolation                   PASS
8.7  policy isolation                     PASS
8.8  audit isolation                      PASS
8.9  credential isolation                 PASS
8.10 cross-tenant references rejected     PASS
8.11 existence leakage prevented          FAIL
8.12 vector isolation                     PASS

Release status: BLOCKED
Blocking requirement: Invariant 08.11
```

A passing-test count alone is not conformance reporting.

## 2.20 Release Conformance Rule

A v1.0 release candidate MUST satisfy all applicable invariant requirements. The minimum gate requires Invariants 01 through 12 to be conformant. A single failed mandatory requirement blocks release-candidate conformance unless an explicitly approved specification exception applies.

The following do not qualify as conformance: mostly passing, known limitation, accepted technical debt, will fix after launch, not expected in production, or works under normal conditions.

## 2.21 Contract-Test Organization

Contract tests MUST be organized by invariant:

```text
tests/contracts/
|- invariant_01_verdict_authority.py
|- invariant_02_safe_failure.py
|- invariant_03_evidence_semantics.py
|- invariant_04_durable_results.py
|- invariant_05_webhook_independence.py
|- invariant_06_evidence_integrity.py
|- invariant_07_policy_immutability.py
|- invariant_08_tenant_isolation.py
|- invariant_09_credential_separation.py
|- invariant_10_bounded_policy_evaluation.py
|- invariant_11_result_accessibility.py
`- invariant_12_audit_completeness.py
```

Each module MUST map tests to normative requirement identifiers, such as `test_8_1_tenant_id_required()` and `test_8_3_tenant_derived_from_principal()`.

## 2.22 Test Infrastructure Requirement

Contract tests MUST be supported by dedicated infrastructure capable of exercising semantic contracts independently of production infrastructure where appropriate. It SHOULD provide a contract runner, synthetic evidence generators, malformed/adversarial input generators, mock policy repository, deterministic Decision Engine harness, mock evidence storage, mock webhook endpoint, mock principals, multi-tenant fixtures, fault injection, audit inspection, and result-provenance inspection.

Test infrastructure MUST NOT weaken the semantics being tested. Mocks MUST model relevant contract behavior rather than simply returning successful responses.

## 2.23 Architectural Conformance Principle

The enforceable chain is:

```text
Architectural Invariant
        |
Normative Requirement
        |
Contract Test
        |
Implementation
        |
Conformance Report
        |
Release Gate
```

The absence of a contract test for a normative requirement SHOULD be treated as a coverage gap. The absence of a normative requirement for a critical guarantee SHOULD be treated as a specification gap.

## 2.24 Summary of v1.0 Invariants

| ID | Invariant | Core guarantee |
|---|---|---|
| 01 | Verdict Authority | Only the Decision Engine produces final verification verdicts |
| 02 | Safe Decision Failure | Unsafe decision execution becomes `INCONCLUSIVE` |
| 03 | Explicit Evidence Semantics | Evidence states are explicit and never implicitly conflated |
| 04 | Durable Results | Results are persisted before webhook delivery |
| 05 | Webhook Independence | Webhook failure cannot alter verification |
| 06 | Evidence Integrity | Evidence is immutable and integrity-verifiable |
| 07 | Policy Immutability | Activated policy versions cannot be mutated |
| 08 | Tenant Isolation | Tenant boundaries are enforced throughout the system |
| 09 | Credential Separation | Operational credentials cannot exercise governance authority |
| 10 | Bounded Policy Evaluation | Policy execution is finite, validated, and runtime-bounded |
| 11 | Result Accessibility | Durable results remain retrievable independently of webhooks |
| 12 | Audit Completeness | Relevant actions are durably audited before external effects |

## 2.25 Constitutional Priority

Where behaviors appear to conflict, priority is:

```text
Architectural Invariants
        |
Semantic Definitions
        |
API Contract
        |
Domain/Application Rules
        |
Infrastructure Implementation
        |
Operational Convenience
```

Operational convenience MUST NOT override an architectural invariant. Implementation simplicity MUST NOT override a safety invariant. Performance optimization MUST NOT silently weaken evidence, authorization, audit, or decision semantics. Unsuitable constraints MUST be changed through governance, never bypassed through implementation.

## End of Part II

Part II establishes the normative architectural constitution of Averiq v1.0. Subsequent semantic definitions, API contracts, implementations, and contract tests MUST conform to these twelve invariants.
