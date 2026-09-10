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

The dependency order is a semantic reading order, not a claim that later invariants are optional or that earlier invariants are independent. Invariant 12 is the final numbered invariant and is cross-cutting: its audit-before-effect, attribution, durability, integrity, tenant, privacy, and conformance requirements apply to the governed actions of the other invariants.

The normative Part evaluation order is:

```text
Part II Architectural Invariants
        -> Part III Evidence Semantics
        -> Part IV Verification Workflow
        -> Part V Decision Engine
        -> Part VI API Contract
        -> Part VII Security and Governance
        -> Part VIII Conformance
        -> Part IX Deferred Architecture
        -> Part X Reliability and Operations
        -> Part XI Data Protection and Privacy
```

Later Parts refine and operationalize earlier Parts; they MUST NOT weaken them. All applicable Parts MUST be evaluated during conformance, including Parts X and XI.

Normative requirement identifiers are globally namespaced by Part. Part II requirements use `INV-<invariant>.<requirement>` identifiers, while other Parts use their declared prefixes such as `EVD-*`, `WF-*`, `DEC-*`, `API-*`, `SEC-*`, `CONF-*`, `DEF-*`, `REL-*`, and `PRV-*`. Legacy numeric references in this document map to the corresponding `INV-*` identifier.
Transaction-critical audit is required for any action whose externally observable effect changes verification, evidence, policy, credential, tenant, security, privacy, lifecycle, or administrative state. Best-effort audit is permitted only for non-blocking diagnostic or supplementary events that are not required to establish the governed effect. The classification MUST be approved in the versioned audit taxonomy and MUST NOT be selected merely to avoid blocking an action.

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

**Exception status:** No exception is approved for v1.0. Any future exception MUST follow Appendix A governance.

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

**Exception status:** No safety-failure exception is permitted. Any proposed exception MUST follow Appendix A governance and cannot authorize unsafe verdicts.

## 2.6 Invariant 03 - Explicit Evidence Semantics

**Status: PREREQUISITE: v1.0**

Evidence absence, non-requirement, failure, unavailability, and inconclusiveness are distinct semantic states and MUST NOT be implicitly conflated. The closed evidence vocabulary includes `PASS`, `FAIL`, `INCONCLUSIVE`, `NOT_REQUIRED`, `NOT_SUBMITTED`, and `UNAVAILABLE` as defined by Part III. `NOT_RUN` is reserved for internal processing execution state and is not an evidence status.

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

**Exception status:** No evidence-state ambiguity exception is permitted. Any proposed exception MUST follow Appendix A governance.

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

**Exception status:** No result/webhook ordering exception is approved. Any proposed exception MUST follow Appendix A governance.

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

**Exception status:** No verification-result independence exception is approved. Any proposed exception MUST follow Appendix A governance.

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

**Exception status:** Authorized evidence deletion is a lifecycle operation, not an exception to immutability. Other exceptions require Appendix A approval and registration.

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

**Exception status:** No activated-policy mutation exception is approved. Any proposed exception MUST follow Appendix A governance.

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

**Exception status:** No implicit cross-tenant access is permitted. Any future capability requires Appendix A governance, explicit authorization, auditability, and isolation.

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

**Exception status:** No privilege-separation exception is approved. Any proposed exception MUST follow Appendix A governance.

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

**Exception status:** No arbitrary-code or unbounded-policy exception is permitted. Any proposed exception MUST follow Appendix A governance.

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

**Exception status:** Temporary platform outage is not a semantic exception if the result remains durably persisted and becomes retrievable after recovery. Other exceptions require Appendix A governance.

## 2.15 Invariant 12 - Audit Completeness

**Status: PREREQUISITE: v1.0**

Every verification-relevant, governance-relevant, and authorization-relevant action MUST leave a durable, integrity-protected audit trail before its governed effects become externally observable. Audit completeness is cross-cutting: it governs the externally observable actions defined by the other invariants without replacing their authority or semantics.

### 12.1 Audit completeness

- **12.1** Every verification-relevant governed action MUST produce a corresponding audit event.
- **12.2** Every governance-relevant governed action MUST produce a corresponding audit event.
- **12.3** Every authorization-relevant governed action MUST produce a corresponding audit event.
- **12.4** Successful and materially failed governed actions MUST be auditable where the action is security-, authorization-, verification-, or governance-relevant.
- **12.5** System-initiated actions MUST be auditable like materially equivalent human-initiated actions.
- **12.6** The audit taxonomy MUST be complete, versioned, and explicit about governed action/event coverage.
- **12.7** The system MUST classify governed audit events as transaction-critical or best-effort with explicit semantics.

### 12.2 Audit event ordering

The normative ordering is:

```text
Action -> Required Audit Event -> Durable Audit Acceptance -> Observable Effect
```

The reverse ordering is prohibited. For a transaction-critical event, the effect MUST NOT proceed until durable acceptance succeeds. Best-effort classification MUST NOT be used to make a required externally observable effect appear durably audited.

- **12.8** A required audit event MUST be durably accepted before its governed externally observable effect.
- **12.9** An operation MUST NOT be reported externally as successful when its required audit event has not been durably accepted.
- **12.10** A required audit event MUST NOT depend solely on an eventually executed background operation after the action is observable.
- **12.11** Audit ordering MUST remain valid during retries, crashes, timeouts, and partial failures.

### 12.3 Durable audit acceptance

In-memory writes and local queues are not durable acceptance. Durability MUST reach the authoritative audit persistence boundary.

- **12.12** A required audit event MUST reach its authoritative durable persistence boundary before the governed effect.
- **12.13** Temporary in-memory buffering MUST NOT satisfy a durable audit requirement.
- **12.14** Audit persistence failure MUST produce explicit failure semantics.
- **12.15** The system MUST NOT silently discard a required audit event.
- **12.16** Audit retries MUST preserve event identity and MUST NOT create contradictory histories.

### 12.4 Audit integrity

Audit integrity MAY use database controls, append-oriented storage, hashes, signatures, immutable storage, controlled permissions, chained references, or an equivalent governed mechanism.

- **12.17** Audit events MUST be protected against unauthorized modification.
- **12.18** Audit events MUST be attributable to an actor or system process.
- **12.19** Audit events MUST contain sufficient context to reconstruct the governed action.
- **12.20** Audit records MUST preserve event ordering information.
- **12.21** Audit integrity mechanisms MUST be protected by appropriate authorization and security controls.
- **12.22** Audit validation MUST reject missing or malformed authorization context, correlation data, integrity metadata, or sanitization output where those fields are required.

### 12.5 Audit event identity

- **12.23** Every audit event MUST have a unique event identifier.
- **12.24** Retrying an operation MUST NOT unintentionally create multiple authoritative representations of the same governed action.
- **12.25** Audit event identity MUST remain stable across permitted retries.
- **12.26** Audit events MUST be correlatable to the relevant request, session, resource, or operation where applicable.

### 12.6 Actor attribution

Valid actor categories include at minimum `HUMAN_OPERATOR`, `SERVICE`, and `SYSTEM`.

- **12.27** Every governed audit event MUST identify its actor type.
- **12.28** Human-initiated actions MUST identify the applicable actor where available.
- **12.29** System-initiated actions MUST identify the responsible process or service context.
- **12.30** Audit records MUST NOT contain raw authentication secrets.
- **12.31** Actor attribution MUST be consistent with `AuthorizationContext`.

### 12.7 Tenant attribution

- **12.32** Every tenant-scoped governed action MUST have an authoritative tenant association.
- **12.33** Tenant attribution MUST derive from trusted authorization context.
- **12.34** Audit retrieval MUST preserve tenant isolation.
- **12.35** A tenant MUST NOT retrieve another tenant's audit records.
- **12.36** Audit infrastructure MUST NOT create a cross-tenant disclosure path.

### 12.8 Verification auditability

Material events MAY include session creation/submission, evidence submission/deletion, processing, provider calls/failures, decision production/persistence/retrieval, webhook dispatch/failure, expiration, cancellation, retention deletion, and automated retries. The vocabulary MAY evolve while preserving semantics.

- **12.37** Material verification lifecycle transitions MUST be auditable.
- **12.38** Material evidence lifecycle operations MUST be auditable.
- **12.39** Material Decision Engine execution and result persistence MUST be auditable.
- **12.40** System-generated lifecycle actions MUST be auditable.
- **12.41** Audit events MUST reference relevant resources without unnecessarily reproducing sensitive contents.

### 12.9 Authorization auditability

- **12.42** Material authorization changes MUST be auditable.
- **12.43** Credential lifecycle operations MUST be auditable.
- **12.44** Privileged administrative actions MUST be auditable.
- **12.45** Policy activation and deactivation MUST be auditable.
- **12.46** Security-relevant authorization failures MUST produce appropriate audit evidence.

### 12.10 Failed actions

- **12.47** Material failed governed actions MUST produce audit events where required by audit scope.
- **12.48** Audit events MUST distinguish successful actions from failed actions.
- **12.49** Audit records MUST preserve the reason or failure category needed for investigation without prohibited sensitive content.
- **12.50** Failed audit persistence MUST NOT be silently converted into successful operation semantics.

### 12.11 Audit and evidence

- **12.51** Audit events MUST NOT be treated as verification evidence.
- **12.52** Raw biometric content MUST NOT be copied into audit events.
- **12.53** Raw identity-document content MUST NOT be copied into audit events.
- **12.54** Audit records MUST preserve traceability references without unnecessarily retaining sensitive evidence.

### 12.12 Audit and decision authority

- **12.55** Audit infrastructure MUST NOT declare verification outcomes.
- **12.56** Audit records MUST NOT be interpreted as independent verification verdicts.
- **12.57** Decision provenance MUST remain attributable to the Decision Engine.
- **12.58** Audit records MUST preserve policy and decision context required by provenance contracts.

### 12.13 Audit and privacy

- **12.59** Audit events MUST contain the minimum sensitive information necessary for accountability.
- **12.60** Audit records MUST be classified and protected according to their contents.
- **12.61** Audit data MUST have defined retention semantics.
- **12.62** Audit retention MUST NOT become an uncontrolled mechanism for retaining deleted biometric or document content.
- **12.63** Privacy controls MUST NOT silently destroy required auditability.

### 12.14 Audit failure semantics

If required audit persistence fails, the governed observable effect MUST be blocked. Audit failure MUST NOT fabricate a verification rejection.

- **12.64** Required audit persistence failure MUST have deterministic semantics.
- **12.65** A required operation MUST NOT become externally successful when its mandatory audit event failed to persist.
- **12.66** Audit persistence failure MUST NOT cause a fabricated verification rejection.
- **12.67** Audit infrastructure failure MUST remain distinguishable from verification failure.
- **12.68** Audit recovery MUST preserve event identity and ordering.

### 12.15 Audit ordering under failure

- **12.69** Process failure MUST NOT result in an externally visible governed action without its required audit event.
- **12.70** Network timeout MUST NOT cause the system to assume required audit persistence.
- **12.71** Retry behavior MUST preserve audit ordering.
- **12.72** Concurrent operations MUST preserve the audit-before-effect relationship.

### 12.16 Audit completeness boundary

Purely internal computations MAY remain outside the audit boundary only when they have no independent verification, authorization, governance, security, privacy, or externally material significance. An implementation MUST NOT classify an action as internal solely to avoid audit.

- **12.73** Audit scope MUST be defined by semantic significance rather than implementation convenience.
- **12.74** Material internal actions affecting governed state MUST remain within the audit boundary.
- **12.75** Audit exclusions MUST be justified where omission could affect reconstruction.

### 12.17 Audit retrieval

- **12.76** Audit retrieval MUST require appropriate authorization.
- **12.77** Audit retrieval MUST enforce tenant isolation.
- **12.78** Audit retrieval MUST NOT expose secrets or unnecessary sensitive content.
- **12.79** Audit retrieval MUST preserve authoritative event identity.
- **12.80** Audit retrieval MUST NOT permit unauthorized modification or deletion.

### 12.18 Audit immutability

- **12.81** Historical audit records MUST NOT be silently rewritten.
- **12.82** Material corrections MUST preserve the original record or equivalent integrity-preserving history.
- **12.83** Audit correction MUST be governed and auditable.

### 12.19 Audit completeness testing

Contract tests MUST verify both:

```text
Action -> Required Audit Event -> Observable Effect
Action -> Audit Persistence Failure -> No Observable Effect
```

- **12.84** Contract tests MUST verify audit-before-effect ordering.
- **12.85** Contract tests MUST verify successful operations.
- **12.86** Contract tests MUST verify materially failed operations.
- **12.87** Contract tests MUST verify persistence failure.
- **12.88** Contract tests MUST verify retries and duplicate requests.
- **12.89** Contract tests MUST verify tenant isolation.
- **12.90** Contract tests MUST verify sensitive-data exclusion.
- **12.91** Contract tests MUST verify retention deletion, automated retry, scheduled processing, tenant configuration, integrity protection, sanitization failure, and audit persistence failure where applicable.

### 12.20 Sub-invariant conformance

- **12.92** Conformance MUST be reported at normative-requirement level.
- **12.93** A failed normative requirement MUST remain visible even when the parent invariant has passing requirements.
- **12.94** Release gating MUST identify the exact failed requirement.
- **12.95** Contract-test output MUST be traceable to the corresponding invariant requirement.
- **12.96** Audit event classification, ordering, durability, integrity, sanitization, authorization context, correlation, and exception reference MUST be reportable where applicable.

### 12.21 Legitimate exceptions

Best-effort events are a defined audit class, not an exception to audit governance. Any exception that relaxes an invariant requirement MUST:

1. have a unique identifier;
2. identify the affected requirement;
3. document the exact behavior and scope;
4. provide architectural justification;
5. document security, reliability, privacy, and trust implications;
6. define compensating controls;
7. identify affected components and tests;
8. receive approval from the designated architecture authority;
9. have explicit status, effective period, and review or expiration date; and
10. be recorded in the Approved Exception Registry (Appendix A).

- **12.97** Every exception to Invariant 12 MUST have a unique identifier.
- **12.98** Every exception MUST contain architectural justification.
- **12.99** Every exception MUST identify affected scope.
- **12.100** Every exception MUST have documented approval and review/expiration semantics.
- **12.101** Every exception MUST be recorded in the Approved Exception Registry (Appendix A).
- **12.102** An implementation MUST NOT silently bypass an audit requirement as an undocumented exception.

### 12.22 Constitutional statement

> **Every verification-relevant, governance-relevant, and authorization-relevant action MUST leave a durable, integrity-protected audit trail before its governed effects become externally observable.**

The audit trail is part of Averiq's trust boundary. Governed actions MUST be reconstructable, attributable, integrity-protected, and auditable without compromising privacy, tenant isolation, reliability, or Decision Engine authority.

**Exception status:** Only formally approved exceptions recorded in the Approved Exception Registry (Appendix A) may relax a normative requirement. Best-effort classification MUST NOT be reported as a waiver or as full durable conformance.

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
10. have an explicit effective period, expiration or review date, and status;
11. be entered into the Approved Exception Registry (Appendix A);
12. state whether it permits governed release without changing requirement-level conformance.

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

A v1.0 release candidate MUST satisfy all applicable invariant requirements. The minimum gate requires Invariants 01 through 12 to be conformant. A single failed mandatory requirement blocks requirement-level conformance. An approved Appendix A exception MAY separately permit a governed release, but MUST NOT convert a failed requirement into `PASS` or `CONFORMANT`.

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

The absence of a contract test for a normative requirement SHOULD be treated as a coverage gap. The absence of a normative requirement for a critical guarantee SHOULD be treated as a specification gap. Audit evidence, requirement status, and approved exceptions MUST be available before release-gate evaluation.

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
| 12 | Audit Completeness | Governed actions are durably audited before observable effects, with explicit transaction-critical and best-effort classifications |

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

## Appendix A - Approved Exception Registry

The Approved Exception Registry is the authoritative record for exceptions that may permit governed release without changing requirement-level conformance.

Each registry entry MUST contain:

```text
Exception
|- exception_id
|- invariant_id
|- requirement_id
|- exact_excepted_behavior
|- architectural_justification
|- security_impact
|- reliability_impact
|- privacy_impact
|- affected_components
|- affected_contract_tests
|- compensating_controls
|- approving_authority
|- effective_date
|- expiration_or_review_date
|- status
`- release_permission
```

An exception MUST state whether it permits a governed release while the affected requirement remains `NONCONFORMANT` or `EXCEPTION_APPROVED`. The designated architecture authority owns approval, and the security, privacy, reliability, and domain owners MUST approve exceptions affecting their control areas. An unregistered, expired, or undocumented exception MUST NOT permit release or be reported as conformance.

No exception may permit release against a failure of Decision Engine verdict authority, tenant isolation, audit-before-effect ordering, raw secret or raw biometric/document exclusion, or a requirement explicitly marked non-waivable by the applicable Part. These requirements are release-blocking and cannot be converted to `PASS` by exception.

## End of Part II

Part II establishes the normative architectural constitution of Averiq v1.0. Subsequent semantic definitions, API contracts, implementations, and contract tests MUST conform to these twelve invariants.
