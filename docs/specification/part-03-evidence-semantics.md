# PaxLI by PaxAlpha

# Decision & Verification Semantics Specification

## Part III - Evidence Semantics

**Semantic Contract:** v1.0  
**Document Status:** Normative  
**Product:** PaxLI by PaxAlpha  
**Positioning:** Identity Verification & Biometric Trust Infrastructure  
**Tagline:** Verify with confidence.

## 3.0 Purpose and Scope

This part defines the normative meaning, lifecycle, integrity, provenance, status semantics, and handling rules for evidence within PaxLI.

Evidence is the primary intermediate representation through which verification components communicate findings to the Decision Engine. Models and verification components produce evidence. The Decision Engine interprets evidence and produces the final verification decision. Evidence MUST NOT itself constitute a final verification verdict.

This part governs evidence identity, types, status and absence, provenance, integrity, immutability, versioning, quality, scores, reason codes, model references, timestamps, relationships, requirements, deletion, retention, access boundaries, and the evidence-to-Decision-Engine contract.

## 3.1 Scope Classification

- **PREREQUISITE: v1.0** means required for v1.0 conformance.
- **TARGET: v1.1** means the semantic direction is defined but implementation is not required for v1.0.
- **FUTURE** means reserved for future architecture and outside the current implementation contract.

A `TARGET` or `FUTURE` capability MUST NOT be treated as an implicit v1.0 requirement.

## 3.2 Definition of Evidence

**Status: PREREQUISITE: v1.0**

Evidence is a structured, attributable representation of an observation, computation, verification result, or externally supplied finding that may be evaluated by the Decision Engine.

Examples include document quality, OCR extraction, document authenticity, face detection, face quality, face embedding generation, face-match comparison, identity consistency, external identity-provider response, and liveness assessment.

Evidence MUST contain sufficient metadata to establish what produced it, what was evaluated, what result was produced, which model or component version was used, when it was produced, what status applies, and whether the result is suitable for decisioning.

### Requirements

- **EVD-3.2.1** Every persisted evidence object MUST have a unique evidence identifier.
- **EVD-3.2.2** Every evidence object MUST identify its evidence type.
- **EVD-3.2.3** Every evidence object MUST have an explicit status appropriate to its evidence type.
- **EVD-3.2.4** Evidence MUST NOT directly represent a final verification verdict.
- **EVD-3.2.5** Evidence MUST be attributable to a verification session or another explicitly authorized parent context.

## 3.3 Evidence Lifecycle

**Status: PREREQUISITE: v1.0**

Evidence moves through a governed lifecycle:

```text
Captured or received
        |
Validated
        |
Processed or evaluated
        |
Produced
        |
Persisted
        |
Interpreted by the Decision Engine
        |
Retained, deleted, or tombstoned under authorization
```

Lifecycle transitions MUST be explicit and auditable where required by Part II. A lifecycle state MUST NOT be inferred from a missing field or an implementation-specific null value.

### Requirements

- **EVD-3.3.1** Evidence lifecycle states MUST be explicitly represented where they affect interpretation or access.
- **EVD-3.3.2** Evidence MUST NOT become decision-relevant before schema and semantic validation succeeds.
- **EVD-3.3.3** Evidence persistence MUST preserve the status and provenance that applied when it was produced.
- **EVD-3.3.4** Evidence deletion MUST be an explicit authorized lifecycle operation.
- **EVD-3.3.5** Lifecycle transitions affecting decision-relevant evidence MUST be auditable according to Part II.

## 3.4 Evidence Identity

**Status: PREREQUISITE: v1.0**

Evidence identity MUST be independent of content. An evidence identifier remains stable for the lifetime of the evidence object and MUST NOT be reused for another object.

### Requirements

- **EVD-3.4.1** Evidence IDs MUST be unique within the PaxLI system.
- **EVD-3.4.2** An evidence ID MUST NOT be reassigned after evidence deletion.
- **EVD-3.4.3** Evidence identity MUST NOT depend solely on a client filename, object-storage key, or external provider identifier.

## 3.5 Evidence Types

**Status: PREREQUISITE: v1.0**

PaxLI MUST use an explicit evidence-type taxonomy. Initial v1.0 domains include:

```text
Evidence
|- Capture: SelfieCapture, DocumentCapture
|- Document: DocumentQuality, DocumentClassification, OCRExtraction,
|            DocumentFieldExtraction, MRZ, Barcode/QR, DocumentAuthenticity
|- Biometric: FaceDetection, FaceQuality, FaceEmbedding, FaceMatch
|- Identity: IdentityConsistency
`- External: ExternalIdentityProvider
```

Liveness/PAD is architecturally supported and may be `TARGET: v1.1` if not activated in v1.0. 1:N identification and biometric deduplication are `FUTURE` unless promoted through specification governance.

### Requirements

- **EVD-3.5.1** Every evidence object MUST declare exactly one canonical evidence type.
- **EVD-3.5.2** Evidence types MUST have defined semantics before being accepted by the Decision Engine.
- **EVD-3.5.3** An implementation MUST NOT introduce an undocumented evidence type into a normative verification decision.

## 3.6 Evidence Status Semantics

**Status: PREREQUISITE: v1.0**

Evidence status describes the state of the evidence-producing operation. Common operational states are:

```text
NOT_REQUIRED
NOT_SUBMITTED
UNAVAILABLE
INCONCLUSIVE
PASS
FAIL
```

Evidence types MAY use domain-specific terminal result labels, such as `MATCH`/`MISMATCH` or `VALID`/`INVALID`, where those labels have materially different semantics. The common semantic rules MUST remain preserved.

Internal execution states such as `NOT_RUN` are not evidence statuses and MUST be mapped to an explicit evidence state before evidence is accepted by the Decision Engine.

### Requirements

- **EVD-3.6.1** Every evidence type MUST define a closed set of valid statuses or results.
- **EVD-3.6.2** Missing, unknown, malformed, or unsupported status MUST NOT be interpreted as `PASS`.
- **EVD-3.6.3** Missing, unknown, malformed, or unsupported status MUST NOT be interpreted as `FAIL`.
- **EVD-3.6.4** Null, a missing field, an empty string, or an equivalent value MUST NOT substitute for a defined evidence state.
- **EVD-3.6.5** Evidence semantics MUST distinguish inability to evaluate from an evaluated negative result.

## 3.7 Evidence Absence Semantics

**Status: PREREQUISITE: v1.0**

The following states are distinct:

- **`NOT_REQUIRED`**: the active policy does not require the evidence. No attempt is required. It is neither success nor failure.
- **`NOT_SUBMITTED`**: required or usable input has not been submitted. It is not equivalent to unavailability.
- **`UNAVAILABLE`**: the capability could not be used because a component or dependency was unavailable. It is not a negative finding.
- **`INCONCLUSIVE`**: processing was attempted or information was available, but a reliable positive or negative result could not be established.
- **`PASS`**: the component established the positive condition defined by its evidence type.
- **`FAIL`**: the component established the negative condition defined by its evidence type. Processing failure alone MUST NOT become `FAIL`.

### Requirements

- **EVD-3.7.1** All six common states MUST remain semantically distinguishable.
- **EVD-3.7.2** Infrastructure failure MUST NOT be represented as `FAIL` unless the evidence specification explicitly defines that meaning.
- **EVD-3.7.3** A component that cannot reliably determine a result MUST return `INCONCLUSIVE` or another explicitly defined non-decisive state.
- **EVD-3.7.4** The Decision Engine MUST interpret these states in the context of policy.

## 3.8 Evidence Provenance

**Status: PREREQUISITE: v1.0**

Decision-relevant evidence MUST be attributable to its source. Provenance SHOULD identify:

```text
Evidence
|- evidence_id
|- evidence_type
|- session_id
|- tenant_id
|- producer
|- producer_version
|- model_reference
|- created_at
|- source_reference
`- integrity_reference
```

Omitted provenance fields MUST be semantically justified for the evidence type.

### Requirements

- **EVD-3.8.1** Evidence MUST identify the component or subsystem that produced it.
- **EVD-3.8.2** Model-generated evidence MUST record model identity and version.
- **EVD-3.8.3** External-provider evidence MUST record provider identity and relevant response reference.
- **EVD-3.8.4** Provenance MUST support reconstruction of the verification decision.

## 3.9 Evidence Integrity

**Status: PREREQUISITE: v1.0**

Evidence integrity is governed by Architectural Invariant 06. Persisted evidence MUST have an integrity-verifiable representation. Stored content SHOULD use a cryptographic digest such as SHA-256. Integrity metadata may include `content_hash`, `hash_algorithm`, `storage_reference`, and `integrity_reference`.

### Requirements

- **EVD-3.9.1** Persisted evidence content MUST have an integrity-verifiable representation.
- **EVD-3.9.2** Integrity metadata MUST correspond to actual persisted content.
- **EVD-3.9.3** An integrity mismatch MUST NOT silently produce trusted evidence.
- **EVD-3.9.4** Integrity failure affecting decision-relevant evidence MUST produce a safe non-verifying outcome such as `INCONCLUSIVE`.
- **EVD-3.9.5** Integrity checks MUST NOT rely exclusively on client-provided hashes.

## 3.10 Evidence Immutability

**Status: PREREQUISITE: v1.0**

Evidence is immutable during its authorized lifecycle. Immutability means an existing evidence object cannot be silently changed into a different observation or result. It does not require indefinite retention; authorized deletion remains possible.

### Requirements

- **EVD-3.10.1** Decision-relevant evidence MUST NOT be silently overwritten.
- **EVD-3.10.2** Evidence status MUST NOT be changed merely to alter a verification result.
- **EVD-3.10.3** A superseding observation MUST be a distinct evidence object or explicitly governed derived evidence.
- **EVD-3.10.4** Evidence mutation APIs MUST NOT expose unrestricted update semantics.

## 3.11 Evidence Versioning

**Status: PREREQUISITE: v1.0**

Evidence schema version, producer/model version, and policy version are separate concepts. For example, `Evidence Schema: 1.0`, `Producer Version: 2.3.1`, `Model Version: model-2026-08`, and `Policy: policy-17 v4` MUST remain distinguishable.

### Requirements

- **EVD-3.11.1** Evidence schema version MUST be independently identifiable where schema evolution affects interpretation.
- **EVD-3.11.2** Producer or model version MUST NOT substitute for schema version.
- **EVD-3.11.3** Policy version MUST remain separate from evidence and model versions.

## 3.12 Evidence Quality

**Status: PREREQUISITE: v1.0**

Quality describes whether an input or observation is suitable for reliable interpretation. Quality is not a final verification decision. A quality assessment MAY cause a component to return `INCONCLUSIVE`.

### Requirements

- **EVD-3.12.1** Quality measurements MUST remain distinguishable from verification outcomes.
- **EVD-3.12.2** Poor quality MUST NOT automatically be represented as identity failure.
- **EVD-3.12.3** Quality thresholds used for decisioning MUST be defined by policy or component semantics, not undocumented constants.
- **EVD-3.12.4** Insufficient quality MUST result in `INCONCLUSIVE` or another explicitly defined non-decisive state.

## 3.13 Evidence Confidence and Scores

**Status: PREREQUISITE: v1.0**

Scores and confidence values are component measurements, not inherently probabilities. A score such as `0.83` MUST NOT be interpreted as an 83% probability unless calibration establishes that meaning.

### Requirements

- **EVD-3.13.1** Every score MUST have documented semantics.
- **EVD-3.13.2** A score MUST NOT be treated as a probability without calibration establishing that interpretation.
- **EVD-3.13.3** Thresholds MUST reference the model, evaluation methodology, population, and operating conditions under which they were established.
- **EVD-3.13.4** The Decision Engine MUST interpret scores according to policy and evidence semantics.
- **EVD-3.13.5** A score alone MUST NOT constitute a final verification verdict.

## 3.14 Evidence Reason Codes

**Status: PREREQUISITE: v1.0**

Evidence MAY contain stable machine-readable reason codes, including `IMAGE_TOO_BLURRY`, `FACE_NOT_DETECTED`, `MULTIPLE_FACES`, `MODEL_UNAVAILABLE`, `MODEL_TIMEOUT`, `OCR_UNREADABLE`, `DOCUMENT_UNSUPPORTED`, `PROVIDER_TIMEOUT`, and `INSUFFICIENT_SIGNAL`.

### Requirements

- **EVD-3.14.1** Decision-relevant reason codes MUST be stable and machine-readable.
- **EVD-3.14.2** Reason codes MUST have defined semantics.
- **EVD-3.14.3** Reason codes MUST NOT expose secrets or unnecessary sensitive information.
- **EVD-3.14.4** Reason codes MUST distinguish operational failure from verification failure where relevant.

## 3.15 Evidence Model References

**Status: PREREQUISITE: v1.0**

Where models produce evidence, PaxLI MUST retain sufficient model-reference metadata to establish which model produced the result. A model reference SHOULD include `model_id`, `model_version`, `runtime`, `runtime_version`, and `configuration_reference` as applicable.

### Requirements

- **EVD-3.15.1** Decision-relevant model-generated evidence MUST identify the model version.
- **EVD-3.15.2** Model replacement MUST NOT make historical evidence appear to have been produced by a new model.
- **EVD-3.15.3** Model references MUST remain available for historical reconstruction according to retention policy.

## 3.16 Evidence Timestamps

**Status: PREREQUISITE: v1.0**

Evidence timestamps distinguish meaningful temporal events, which MAY include `captured_at`, `submitted_at`, `processing_started_at`, `produced_at`, and `persisted_at`.

### Requirements

- **EVD-3.16.1** Decision-relevant evidence MUST have a reliable production timestamp.
- **EVD-3.16.2** Server-controlled timestamps MUST NOT be replaced by untrusted client timestamps where ordering affects security or decision semantics.
- **EVD-3.16.3** Timestamp semantics MUST be explicitly defined for each timestamp field.

## 3.17 Evidence Relationships

**Status: PREREQUISITE: v1.0**

Evidence MAY reference other evidence. Derived evidence MUST remain distinguishable from source evidence. Typical lineages include capture to quality to OCR to identity consistency, or selfie capture to face detection to embedding to face match.

### Requirements

- **EVD-3.17.1** Derived evidence MUST identify source evidence where lineage affects interpretation.
- **EVD-3.17.2** Evidence lineage MUST NOT create circular dependencies that cannot be deterministically resolved.
- **EVD-3.17.3** Deleting source evidence MUST NOT leave derived evidence falsely appearing fully reconstructible.

## 3.18 Evidence Requirements

**Status: PREREQUISITE: v1.0**

The applicable verification policy determines required evidence. Required, optional, and non-required evidence MUST be explicit. If a policy does not require liveness, the corresponding state is `NOT_REQUIRED`, not `UNAVAILABLE`.

### Requirements

- **EVD-3.18.1** Evidence requirements MUST derive from the applicable policy.
- **EVD-3.18.2** The Decision Engine MUST distinguish required evidence from optional or non-required evidence.
- **EVD-3.18.3** Required evidence that is absent MUST NOT silently become `NOT_REQUIRED`.

## 3.19 `NOT_REQUIRED` Semantics

**Status: PREREQUISITE: v1.0**

`NOT_REQUIRED` means that the applicable policy does not require the evidence. It MUST NOT mean unavailable, not submitted, processing failure, or an intentional error skip. It is neither successful nor failed verification evidence.

### Requirements

- **EVD-3.19.1** Components MUST return or be represented as `NOT_REQUIRED` where policy explicitly excludes the evidence.
- **EVD-3.19.2** `NOT_REQUIRED` MUST NOT be interpreted as successful verification evidence.
- **EVD-3.19.3** `NOT_REQUIRED` MUST NOT be interpreted as failed verification evidence.

## 3.20 `NOT_SUBMITTED` Semantics

**Status: PREREQUISITE: v1.0**

`NOT_SUBMITTED` means required or potentially usable input has not been supplied, such as a required document or selfie that was never uploaded.

### Requirements

- **EVD-3.20.1** `NOT_SUBMITTED` MUST remain distinguishable from `UNAVAILABLE`.
- **EVD-3.20.2** `NOT_SUBMITTED` MUST remain distinguishable from `FAIL`.
- **EVD-3.20.3** The Decision Engine MUST determine the consequence of missing required evidence.

## 3.21 `UNAVAILABLE` Semantics

**Status: PREREQUISITE: v1.0**

`UNAVAILABLE` means the required evidence-producing capability could not be used because an inference runtime, provider, storage dependency, or other required capability was unavailable.

### Requirements

- **EVD-3.21.1** Dependency unavailability MUST remain separate from a verified negative finding.
- **EVD-3.21.2** `UNAVAILABLE` MUST NOT automatically map to `REJECTED`.
- **EVD-3.21.3** The applicable policy MUST determine the consequence of unavailable evidence.

## 3.22 `INCONCLUSIVE` Semantics

**Status: PREREQUISITE: v1.0**

`INCONCLUSIVE` means available evidence or processing is insufficient to establish a reliable positive or negative result. It is a first-class safety state.

### Requirements

- **EVD-3.22.1** `INCONCLUSIVE` MUST NOT be treated as `FAIL`.
- **EVD-3.22.2** `INCONCLUSIVE` MUST NOT be treated as `PASS`.
- **EVD-3.22.3** Infrastructure uncertainty MUST use `INCONCLUSIVE` or another explicitly non-verifying state rather than `FAIL`.
- **EVD-3.22.4** The Decision Engine MUST determine the final consequence of inconclusive evidence.

## 3.23 `PASS` and `FAIL` Semantics

**Status: PREREQUISITE: v1.0**

`PASS` and `FAIL` have evidence-type-specific meanings and neither is a final verification verdict. For example, `FaceMatch = FAIL` does not by itself define the complete session outcome; policy may map it to `REJECTED`, `REVIEW_REQUIRED`, or `INCONCLUSIVE`.

### Requirements

- **EVD-3.23.1** Evidence `PASS` MUST have evidence-type-specific positive semantics.
- **EVD-3.23.2** Evidence `FAIL` MUST have evidence-type-specific negative semantics.
- **EVD-3.23.3** Component `PASS` or `FAIL` MUST NOT directly mutate a session into a final verdict.
- **EVD-3.23.4** Only the Decision Engine may produce the final verification outcome.

## 3.24 Invalid Evidence

**Status: PREREQUISITE: v1.0**

Evidence is invalid when it violates schema or semantic contract, including unknown types, missing or invalid statuses, invalid scores, missing provenance, invalid model references, malformed relationships, or failed integrity verification.

### Requirements

- **EVD-3.24.1** Evidence schema MUST be validated before decisioning.
- **EVD-3.24.2** Unknown or invalid-status evidence MUST NOT be decisioned as trusted evidence.
- **EVD-3.24.3** Invalid decision-relevant evidence MUST produce a safe outcome such as `INCONCLUSIVE` with an appropriate reason code.
- **EVD-3.24.4** Evidence validation failures MUST be observable and auditable according to applicable audit requirements.

## 3.25 Evidence Conflicts

**Status: PREREQUISITE: v1.0**

Evidence may disagree, such as `FaceMatch = PASS` with `IdentityConsistency = FAIL`. Conflicts MUST NOT be resolved through implicit precedence. Conflict semantics belong to the Decision Engine and applicable policy.

### Requirements

- **EVD-3.25.1** Conflicting evidence MUST remain individually observable.
- **EVD-3.25.2** A component MUST NOT silently overwrite contradictory evidence.
- **EVD-3.25.3** Conflict resolution MUST be defined by Decision Engine policy.
- **EVD-3.25.4** Unresolvable conflicts MUST produce a safe non-verifying decision such as `INCONCLUSIVE`.

## 3.26 Evidence Deletion

**Status: PREREQUISITE: v1.0**

Evidence deletion is a first-class lifecycle operation and MUST require an explicit lawful or policy-defined basis and authorization. Conceptually:

```text
delete(evidence_id, deletion_basis, authorization_context)
```

### Requirements

- **EVD-3.26.1** Evidence MUST NOT be deleted through unrestricted arbitrary paths.
- **EVD-3.26.2** Deletion MUST identify authorization context.
- **EVD-3.26.3** Deletion MUST identify the applicable deletion basis.
- **EVD-3.26.4** Deletion MUST produce an appropriate durable audit event.
- **EVD-3.26.5** Deletion MUST NOT retroactively alter an already-issued result.

## 3.27 Evidence Tombstones

**Status: PREREQUISITE: v1.0**

PaxLI MAY retain a tombstone where a deleted identifier must remain represented for audit or referential integrity. A tombstone MUST NOT preserve deleted biometric or document content.

```text
EvidenceDeleted
|- evidence_id
|- session_id
|- tenant_id
|- deletion_basis
|- authorized_by
|- requested_at
|- executed_at
`- evidence_integrity_reference
```

### Requirements

- **EVD-3.27.1** A deleted evidence ID MUST remain distinguishable from an active evidence ID.
- **EVD-3.27.2** Tombstones MUST NOT contain deleted biometric or document content.
- **EVD-3.27.3** Tombstones MUST NOT represent deleted evidence as available.
- **EVD-3.27.4** Tombstone retention MUST follow audit and privacy requirements.

## 3.28 Evidence Retention

**Status: PREREQUISITE: v1.0**

Evidence retention and immutability are separate concerns. Retention is governed by applicable law, contractual requirements, tenant policy, security requirements, and operational requirements. PaxLI MUST support jurisdiction-specific retention and deletion rules and MUST NOT hard-code one jurisdiction as universally applicable.

### Requirements

- **EVD-3.28.1** Evidence MUST have an appropriate retention policy or classification.
- **EVD-3.28.2** Expired evidence MUST be eligible for authorized deletion.
- **EVD-3.28.3** Retention policy MUST NOT silently override a legally or contractually required deletion process.

## 3.29 Evidence Access Boundaries

**Status: PREREQUISITE: v1.0**

Evidence is highly sensitive. Every evidence access path MUST respect tenant and authorization boundaries.

### Requirements

- **EVD-3.29.1** Tenant-owned evidence MUST be isolated by tenant boundary.
- **EVD-3.29.2** A caller MUST NOT retrieve another tenant's evidence by manipulating an evidence ID.
- **EVD-3.29.3** Authorization MUST derive from the authenticated security principal, not a client tenant identifier.
- **EVD-3.29.4** Evidence APIs MUST NOT expose raw biometric or document content without required authorization.
- **EVD-3.29.5** Evidence MUST NOT be unnecessarily included in logs, exceptions, metrics, or audit metadata.
- **EVD-3.29.6** Future vector or biometric search MUST enforce the same tenant boundary.

## 3.30 Evidence to Decision Engine Contract

**Status: PREREQUISITE: v1.0**

The required flow is:

```text
Capture
   |
Processing Component
   |
Evidence
   |
Evidence Validation
   |
Decision Engine
   |
Verification Decision
```

A component MUST NOT directly return `REJECTED` or `VERIFIED`. For example, `FaceMatchEvidence(status=PASS, score=0.83)` and `LivenessEvidence(status=UNAVAILABLE)` are evidence for policy evaluation, not final verdicts.

### Requirements

- **EVD-3.30.1** Only the Decision Engine may produce the final verification verdict.
- **EVD-3.30.2** Decision-relevant evidence MUST be validated before evaluation.
- **EVD-3.30.3** The Decision Engine MUST receive explicit evidence semantics rather than infer them from missing fields.
- **EVD-3.30.4** The Decision Engine MUST have the applicable policy version.
- **EVD-3.30.5** The resulting decision MUST retain provenance identifying evidence and policy used.

## 3.31 Evidence API Contract

**Status: PREREQUISITE: v1.0**

The public Evidence API MUST expose only semantics required by authorized clients. Internal evidence MAY contain more information than the public API. Evidence retrieval SHOULD normally occur through the authorized verification-session representation rather than unrestricted evidence-object access. Management operations belong to the separate Management API.

Potential operational endpoints include:

```text
POST /v1/verification-sessions/{id}/selfie
POST /v1/verification-sessions/{id}/document
GET  /v1/verification-sessions/{id}
```

### Requirements

- **EVD-3.31.1** Evidence API responses MUST enforce tenant authorization.
- **EVD-3.31.2** Evidence API responses MUST follow the common API error contract.
- **EVD-3.31.3** Evidence APIs MUST NOT expose secrets, raw credentials, stack traces, or unnecessary sensitive implementation metadata.
- **EVD-3.31.4** Evidence submission MUST support platform idempotency semantics where retryable.
- **EVD-3.31.5** Evidence APIs MUST distinguish client submission errors from processing uncertainty.

## 3.32 Evidence Conformance Requirements

**Status: PREREQUISITE: v1.0**

Evidence implementations MUST conform before production decisioning. Conformance MUST be reported at requirement level, for example:

```text
EVD-3.x.1   PASS
EVD-3.x.2   PASS
EVD-3.y.1   PASS
EVD-3.z.1   PASS
EVD-3.w.1   PASS
```

### Requirements

- **EVD-3.32.1** Every normative evidence requirement MUST have a conformance test or formally justified verification method.
- **EVD-3.32.2** Evidence contract tests MUST validate semantic behavior, not merely object shape.
- **EVD-3.32.3** Malformed and adversarial evidence inputs MUST be included.
- **EVD-3.32.4** Evidence integrity failures MUST be tested.
- **EVD-3.32.5** Status confusion cases MUST distinguish `NOT_REQUIRED`, `NOT_SUBMITTED`, `UNAVAILABLE`, `INCONCLUSIVE`, `PASS`, and `FAIL`.
- **EVD-3.32.6** Cross-tenant evidence access MUST be tested.
- **EVD-3.32.7** Evidence deletion and tombstone behavior MUST be tested.

A failed normative evidence requirement blocks the affected release scope unless an approved exception exists in the Approved Exception Registry defined by Part II.

## 3.33 Deferred Evidence Capabilities

### Liveness / Presentation Attack Detection

**Status: TARGET: v1.1**

The architecture SHOULD support passive PAD, temporal analysis, active challenge, replay detection, screen and print attacks, injection attacks, and synthetic-media attacks. A liveness component MUST distinguish `LOW_CONFIDENCE` from `ATTACK_DETECTED`; poor capture quality MUST NOT automatically be treated as an attack.

### External Identity Provider Evidence

**Status: TARGET: v1.1**

Adapters such as NIMC or BVN SHOULD produce standardized external-provider evidence while preserving provider-specific provenance. Provider failures MUST use the reliability semantics established elsewhere in the Semantic Contract.

### 1:N Identification Evidence

**Status: FUTURE**

1:N search and biometric deduplication are distinct from 1:1 verification. If introduced, they MUST have explicit search semantics, authorization boundaries, tenant isolation, candidate-ranking semantics, calibration requirements, false-match controls, and dedicated governance. A 1:1 implementation MUST NOT implicitly become a 1:N search system.

## 3.34 Normative Evidence Object

A conceptual v1.0 evidence object is:

```text
Evidence
|- evidence_id
|- evidence_type
|- schema_version
|- session_id
|- tenant_id
|- status
|- result
|- reason_codes[]
|- score
|- quality
|- producer
|- producer_version
|- model_reference
|- source_reference
|- parent_evidence_ids[]
|- produced_at
|- persisted_at
|- integrity_reference
`- retention_reference
```

Not every field is mandatory for every type. The normative requirement is that each evidence object contain all information necessary to interpret its semantics safely and reconstruct its provenance, with fields appropriate to its type.

## 3.35 Evidence Semantic Rules Summary

1. Evidence is not a verdict.
2. Evidence status is explicit.
3. Absence is not failure.
4. Unavailability is not failure.
5. Inconclusive is not failure.
6. Not required is not success.
7. A score is not automatically a probability.
8. A component result is not a final decision.
9. Evidence is attributable.
10. Evidence is integrity-verifiable.
11. Decision-relevant evidence is immutable during its authorized lifecycle.
12. Authorized deletion does not violate immutability.
13. Deleted evidence must not silently remain available.
14. Conflicts are resolved by policy, not accidental precedence.
15. Evidence remains tenant-isolated.
16. Historical evidence remains distinguishable from newly produced evidence.
17. The Decision Engine alone converts evidence into a final outcome.

## 3.36 Relationship to Architectural Invariants

This part defines the evidence semantics required by Part II:

| Architectural invariant | Evidence implication |
|---|---|
| 01 - Verdict Authority | Evidence cannot produce final verdicts. |
| 02 - Safe Decision Failure | Invalid or insufficient evidence cannot produce unsafe decisions. |
| 03 - Explicit Evidence Semantics | Status and absence states are explicit. |
| 06 - Evidence Integrity | Evidence is integrity-verifiable and immutable. |
| 07 - Policy Immutability | Evidence is interpreted under an immutable policy version. |
| 08 - Tenant Isolation | Evidence access is tenant-scoped. |
| 12 - Audit Completeness | Evidence lifecycle actions require durable auditability. |

Part III depends on Part II and MUST NOT be interpreted independently of the architectural invariants.

## 3.37 Constitutional Principle

> **PaxLI must never infer certainty from ambiguity.**

When evidence establishes a condition, PaxLI records that condition. When evidence establishes a negative condition, PaxLI records that condition. When the system cannot reliably establish either, it records uncertainty explicitly. The Decision Engine then makes the controlled decision permitted by policy.

**Evidence describes what PaxLI knows. The Decision Engine determines what PaxLI decides.**

## End of Part III
