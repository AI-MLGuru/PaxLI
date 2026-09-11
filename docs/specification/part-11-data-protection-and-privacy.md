# PaxLI by PaxAlpha

# Decision & Verification Semantics Specification

## Part XI - Data Protection & Privacy

**Semantic Contract:** v1.0  
**Document Status:** Normative  
**Requirement Prefix:** `PRV-*`  
**Product:** PaxLI by PaxAlpha

## 11.0 Purpose and Scope

This part defines the normative data-protection and privacy semantics governing how PaxLI collects, classifies, processes, accesses, protects, retains, discloses, derives, migrates, restores, and disposes of data.

It applies to identity and biometric information, documents and media, evidence, verification and audit metadata, security records, telemetry, tenant configuration, derived/model information, backups, external-provider data, and research/evaluation data. It MUST be interpreted with Parts II-X. Privacy is a system property, not documentation alone.

### Requirements

- **PRV-11.0.1** PaxLI MUST define and enforce data-protection semantics for all processed data classes.
- **PRV-11.0.2** Privacy controls MUST apply throughout the complete lifecycle.
- **PRV-11.0.3** Privacy controls MUST NOT weaken tenant isolation, security, auditability, or Decision Engine authority.
- **PRV-11.0.4** Data-protection requirements MUST be testable at implementation and operational boundaries.

## 11.1 Privacy Principles

PaxLI applies purpose limitation, minimization, least privilege, tenant isolation, controlled retention, secure processing, lifecycle accountability, traceability, privacy-safe observability, controlled secondary use, privacy by design, and privacy by default.

### Requirements

- **PRV-11.1.1** PaxLI MUST process only data necessary for an authorized purpose.
- **PRV-11.1.2** Access MUST be limited to authorized actors and purposes.
- **PRV-11.1.3** Privacy-sensitive defaults MUST be restrictive.
- **PRV-11.1.4** Secondary use MUST NOT be inferred from technical availability.
- **PRV-11.1.5** Privacy protections MUST remain effective during operation, failure, recovery, migration, and debugging.

## 11.2 Data Protection Governance

The v1.0 Nigerian deployment MUST operate under applicable Nigerian data-protection law and regulatory requirements, including the Nigeria Data Protection Act and competent-authority guidance. Future jurisdictions use explicit extensions rather than informal assumptions.

### Requirements

- **PRV-11.2.1** Applicable jurisdiction MUST be identifiable for each production deployment.
- **PRV-11.2.2** Jurisdiction-specific requirements MUST use governed configuration or policy.
- **PRV-11.2.3** Extensions MUST NOT silently weaken baseline controls.
- **PRV-11.2.4** Material regulatory changes MUST trigger privacy-impact review.
- **PRV-11.2.5** Privacy governance decisions MUST be auditable.
- **PRV-11.2.6** Where requirements conflict, the stricter applicable legal, contractual, platform, or tenant control MUST prevail unless a formally governed rule establishes another lawful precedence.
- **PRV-11.2.7** Jurisdiction, tenant, and processing-purpose precedence MUST be deterministic and auditable.

## 11.3 Data Classification

Baseline classifications are:

| Classification | Meaning |
|---|---|
| `PUBLIC` | Intentionally suitable for unrestricted disclosure |
| `INTERNAL` | Operational information not intended for public disclosure |
| `SENSITIVE` | Personal, identity, tenant, or business-sensitive information |
| `HIGHLY_SENSITIVE` | Biometrics, documents, credentials, secrets, and equivalent data |

Classification attaches to handling rules, not merely database tables.

### Requirements

- **PRV-11.3.1** Every persisted data category MUST have a defined classification.
- **PRV-11.3.2** Highly sensitive data MUST receive stronger controls than sensitive data.
- **PRV-11.3.3** Classification MUST propagate to derived representations where applicable.
- **PRV-11.3.4** Missing classification MUST NOT imply `PUBLIC`.

## 11.4 Data Categories

PaxLI distinguishes identity, biometric, document/media, evidence, verification metadata, operational metadata, audit, security, credential, tenant configuration, derived/model, and backup data.

### Requirements

- **PRV-11.4.1** Categories MUST NOT be treated as interchangeable.
- **PRV-11.4.2** Each category MUST have access, retention, and deletion semantics.
- **PRV-11.4.3** Derived data MUST retain source and processing lineage where required.
- **PRV-11.4.4** Category boundaries MUST be represented in implementation and tests.

## 11.5 Identity Data

Identity data may include names, dates of birth, identity numbers, nationality, address, provider references, and subject identifiers. It is `SENSITIVE` unless more restrictive classification applies.

### Requirements

- **PRV-11.5.1** Identity data MUST be processed only for authorized verification or management purpose.
- **PRV-11.5.2** Identity numbers MUST NOT appear in ordinary logs.
- **PRV-11.5.3** Identity data MUST NOT appear in generic errors.
- **PRV-11.5.4** Identity attributes MUST be returned only when required by authorized operation.
- **PRV-11.5.5** Identity data MUST be tenant-scoped where tenant ownership applies.

## 11.6 Biometric Data

Biometrics include facial images, templates, embeddings, liveness representations, quality measurements, and comparison outputs that contribute to identity inference. They are `HIGHLY_SENSITIVE`. Embeddings MUST NOT be assumed irreversible or anonymous merely because they are transformed.

### Requirements

- **PRV-11.6.1** Biometric data MUST receive highly sensitive controls.
- **PRV-11.6.2** Biometric data MUST NOT appear in ordinary logs.
- **PRV-11.6.3** Raw or derived biometric data MUST NOT appear in audit-event payloads; audit MUST use non-sensitive references and classifications instead.
- **PRV-11.6.4** Biometric data MUST NOT be used outside authorized purpose without governance.
- **PRV-11.6.5** Derived biometric representations MUST retain protections appropriate to identity-inference risk.
- **PRV-11.6.6** Cross-tenant biometric access MUST remain prohibited unless explicitly activated through Part IX specification governance with authorization, auditing, and isolation controls.
- **PRV-11.6.7** Biometric search MUST follow Parts VII and IX.

## 11.7 Document and Media Data

Identity documents, selfies, videos, images, scans, and related media are `HIGHLY_SENSITIVE` unless stricter classification applies.

### Requirements

- **PRV-11.7.1** Uploaded media MUST be treated as untrusted input.
- **PRV-11.7.2** Raw media MUST NOT appear in logs.
- **PRV-11.7.3** Raw media MUST NOT be embedded in any audit event.
- **PRV-11.7.4** Media access MUST require explicit authorization.
- **PRV-11.7.5** Media retention MUST be governed independently from metadata where required.
- **PRV-11.7.6** Temporary processing copies MUST follow lifecycle and deletion requirements.

## 11.8 Verification Metadata

Verification metadata includes session, timestamp, processing, evidence, result, policy, model, reason-code, duration, and provider references.

### Requirements

- **PRV-11.8.1** Metadata MUST be minimized to operational or legal need.
- **PRV-11.8.2** Metadata MUST NOT substitute unrestrictedly for sensitive evidence.
- **PRV-11.8.3** Metadata access MUST respect tenant and authorization boundaries.
- **PRV-11.8.4** Sensitive metadata MUST follow its classification.

## 11.9 Operational Metadata

Operational metadata may include request/correlation IDs, durations, status, errors, versions, device class, network characteristics, and resource utilization. It MUST NOT become unrestricted behavioral profiling.

### Requirements

- **PRV-11.9.1** Operational metadata MUST have a documented purpose.
- **PRV-11.9.2** Collection MUST be proportionate to purpose.
- **PRV-11.9.3** Device and network metadata MUST NOT be collected solely for unnecessary fingerprinting.
- **PRV-11.9.4** Operational metadata MUST NOT contain raw identity numbers, biometrics, documents, or credentials.
- **PRV-11.9.5** Operational retention MUST be independently governed.

## 11.10 Audit and Security Data

Audit and security records provide accountability but remain privacy-protected.

### Requirements

- **PRV-11.10.1** Audit records MUST establish what occurred without unnecessarily reproducing sensitive content.
- **PRV-11.10.2** Raw biometric and document content MUST NOT be stored in any audit event.
- **PRV-11.10.3** Credentials and secrets MUST NOT appear in audit records.
- **PRV-11.10.4** Audit retention MUST be governed independently from evidence retention where appropriate.
- **PRV-11.10.5** Security records MUST receive sensitivity-appropriate access controls.

## 11.11 Tenant Data Ownership and Responsibility

Tenant context defines the authorization boundary for tenant-owned resources.

### Requirements

- **PRV-11.11.1** Tenant-owned resources MUST have authoritative tenant association.
- **PRV-11.11.2** Client tenant identifiers MUST NOT override authenticated context.
- **PRV-11.11.3** Tenant access MUST be enforced across API, storage, audit, cache, background processing, and administration.
- **PRV-11.11.4** Cross-tenant access MUST fail closed.
- **PRV-11.11.5** Tenant deletion or suspension MUST define downstream data effects.

## 11.12 Purpose Limitation

Every material processing operation MUST have an identifiable purpose, such as verification, fraud prevention, audit, security, reliability, compliance, or authorized administration.

### Requirements

- **PRV-11.12.1** Data MUST NOT be processed for unrelated purpose merely because it is available.
- **PRV-11.12.2** New material purposes MUST undergo governance review.
- **PRV-11.12.3** Purpose changes MUST be traceable.
- **PRV-11.12.4** Technical reuse MUST NOT authorize purpose reuse.

## 11.13 Data Minimization

PaxLI minimizes collection, storage, duplication, exposure, retention, transmission, and logging.

### Requirements

- **PRV-11.13.1** APIs MUST request only fields necessary for the operation.
- **PRV-11.13.2** Services MUST receive only required data.
- **PRV-11.13.3** Logs MUST contain only information required for operations.
- **PRV-11.13.4** Temporary copies MUST be minimized.
- **PRV-11.13.5** Minimization MUST be evaluated during architecture changes.

## 11.14 Lawful and Authorized Processing

Technical authorization is distinct from legal basis. Valid API credentials do not establish that every contemplated processing purpose is lawful.

### Requirements

- **PRV-11.14.1** Processing MUST occur only within authorized operational purpose.
- **PRV-11.14.2** Applicable legal and organizational requirements MUST be represented in governance.
- **PRV-11.14.3** System authorization MUST NOT imply universal legal authorization.
- **PRV-11.14.4** Material purpose changes MUST trigger review.

## 11.15 Consent and Other Processing Bases

Consent is distinct from authentication, authorization, and technical-term acceptance. Where another lawful basis applies, processing MUST NOT be falsely represented as consent-based.

### Requirements

- **PRV-11.15.1** Consent records MUST be distinguishable from API authorization.
- **PRV-11.15.2** Consent state MUST be auditable where PaxLI records it.
- **PRV-11.15.3** Withdrawal MUST have defined semantics where applicable.
- **PRV-11.15.4** PaxLI MUST NOT fabricate consent records.
- **PRV-11.15.5** Consent MUST NOT be inferred from silence unless governed as permitted.

## 11.16 Collection Boundaries

Collection channels may include API, SDKs, management interfaces, providers, and internal services.

### Requirements

- **PRV-11.16.1** Each channel MUST enforce classification and validation.
- **PRV-11.16.2** Untrusted input MUST NOT bypass privacy controls.
- **PRV-11.16.3** Additional collection MUST have explicit implementation support.
- **PRV-11.16.4** Unsupported fields MUST be rejected or safely ignored under the API contract.

## 11.17 Data Submission Boundaries

Evidence submission remains distinct from processing and decisioning.

### Requirements

- **PRV-11.17.1** Submission MUST NOT imply authorization for unrelated processing.
- **PRV-11.17.2** Evidence MUST inherit session and tenant privacy context.
- **PRV-11.17.3** Evidence MUST NOT be silently copied into unrelated stores.
- **PRV-11.17.4** Temporary processing data MUST follow defined lifecycle semantics.

## 11.18 Data Access Control

Access is based on authenticated actor, authorization context, tenant, ownership, permission, and purpose where applicable.

### Requirements

- **PRV-11.18.1** Authentication MUST NOT imply authorization.
- **PRV-11.18.2** Authorization MUST precede sensitive access.
- **PRV-11.18.3** Privileged access decisions MUST be auditable.
- **PRV-11.18.4** Access MUST fail closed when authorization context cannot be established.
- **PRV-11.18.5** Sensitive data MUST NOT be returned merely because a caller knows its identifier.

## 11.19 Tenant Isolation and Privacy Boundaries

Tenant isolation is both security and privacy.

### Requirements

- **PRV-11.19.1** Tenant A MUST NOT access Tenant B identity data.
- **PRV-11.19.2** Tenant A MUST NOT access Tenant B evidence.
- **PRV-11.19.3** Tenant A MUST NOT access Tenant B biometric representations.
- **PRV-11.19.4** Unauthorized responses MUST NOT reveal Tenant B resource existence.
- **PRV-11.19.5** Isolation MUST apply to caches, queues, storage, databases, and background processing.
- **PRV-11.19.6** Cross-tenant biometric search MUST remain disabled unless explicitly activated through Part IX governance with dedicated authorization, auditing, and isolation.

## 11.20 Internal Data Access

Internal services receive only data required for assigned operations.

### Requirements

- **PRV-11.20.1** Internal access MUST use explicit service identity.
- **PRV-11.20.2** Internal services MUST NOT receive unrestricted database access by default.
- **PRV-11.20.3** Highly sensitive data MUST have narrower access than operational data.
- **PRV-11.20.4** Materially sensitive internal access MUST be auditable.

## 11.21 Administrative Access

Administrative access is privileged and controlled.

### Requirements

- **PRV-11.21.1** Administrative access MUST be separate from operational credentials.
- **PRV-11.21.2** Highly sensitive administrative access MUST require explicit authorization.
- **PRV-11.21.3** Privileged access MUST be auditable.
- **PRV-11.21.4** Administrative convenience MUST NOT bypass tenant isolation.
- **PRV-11.21.5** Support personnel MUST NOT receive unrestricted raw biometric access by default.

## 11.22 Data in Transit

Sensitive data MUST be protected during transmission.

### Requirements

- **PRV-11.22.1** Production sensitive transport MUST use authenticated secure transport.
- **PRV-11.22.2** Sensitive data MUST NOT use insecure fallback protocols.
- **PRV-11.22.3** Internal transport MUST follow the deployment threat model.
- **PRV-11.22.4** Certificate and transport failures MUST fail safely.

## 11.23 Data at Rest

Sensitive data MUST be protected at rest.

### Requirements

- **PRV-11.23.1** Highly sensitive persisted data MUST use appropriate cryptographic protection.
- **PRV-11.23.2** Encryption keys MUST remain separate from application data.
- **PRV-11.23.3** Application code MUST NOT require raw master-key access.
- **PRV-11.23.4** Encryption failure MUST NOT silently result in plaintext persistence.
- **PRV-11.23.5** Backup copies MUST receive equivalent protection.

## 11.24 Cryptographic Protection

Cryptography follows Part VII and SHOULD use operation-based abstractions compatible with KMS, Vault, or HSM systems.

### Requirements

- **PRV-11.24.1** Key material MUST NOT be logged.
- **PRV-11.24.2** Key material MUST NOT be embedded in source.
- **PRV-11.24.3** Cryptographic operations MUST use controlled interfaces.
- **PRV-11.24.4** Rotation MUST preserve accessibility or provide governed migration.
- **PRV-11.24.5** Cryptographic failure MUST fail closed for protected storage.

## 11.25 Biometric Protection

Biometric representations require elevated protection because they remain associated with identity.

### Requirements

- **PRV-11.25.1** Biometric representations MUST follow `HIGHLY_SENSITIVE` controls.
- **PRV-11.25.2** Biometric representations MUST NOT be treated as ordinary cache data.
- **PRV-11.25.3** Biometric exports MUST be explicitly governed.
- **PRV-11.25.4** Biometric access MUST be tenant-scoped.
- **PRV-11.25.5** Processing MUST retain sufficient authorized provenance.
- **PRV-11.25.6** Protection MUST account for identity-inference risk from derived representations.

## 11.26 Evidence Storage

Evidence storage follows Part III semantics.

### Requirements

- **PRV-11.26.1** Evidence MUST have explicit retention semantics.
- **PRV-11.26.2** Evidence MUST be protected from cross-tenant access.
- **PRV-11.26.3** Object storage MUST NOT be directly exposed without authorization.
- **PRV-11.26.4** Storage references MUST NOT become unrestricted access credentials.
- **PRV-11.26.5** Evidence access MUST be traceable where required.

## 11.27 Data Retention

Retention is purpose-specific. Indefinite retention MUST NOT be the default merely because future use might be useful.

### Requirements

- **PRV-11.27.1** Every retained sensitive category MUST have a retention basis.
- **PRV-11.27.2** Retention periods MUST be configurable where requirements differ.
- **PRV-11.27.3** Retention MUST NOT exceed governing purpose without justification.
- **PRV-11.27.4** Expired data MUST enter governed deletion or archival.
- **PRV-11.27.5** Retention enforcement MUST apply to primary and applicable secondary storage.

## 11.28 Retention Policy

Retention policies are explicit, versioned, and auditable.

### Requirements

- **PRV-11.28.1** Policy changes MUST be traceable.
- **PRV-11.28.2** New periods MUST NOT silently rewrite historical governance without migration rule.
- **PRV-11.28.3** Evaluation MUST be deterministic.
- **PRV-11.28.4** Retention failures MUST alert where required.
- **PRV-11.28.5** Failure MUST NOT produce false deletion claims.

## 11.29 Data Deletion

Deletion is a lifecycle operation and MAY require coordinated removal from database, object storage, caches, temporary stores, indexes, derived stores, replicas, and backups under governed semantics.

### Requirements

- **PRV-11.29.1** Deletion MUST identify affected scope.
- **PRV-11.29.2** Deletion MUST require appropriate authorization.
- **PRV-11.29.3** Deletion MUST be auditable.
- **PRV-11.29.4** Deletion MUST NOT silently leave active copies in governed stores.
- **PRV-11.29.5** Impractical backup deletion MUST have backup-specific lifecycle semantics.
- **PRV-11.29.6** Complete deletion MUST NOT be reported before scope is satisfied.

## 11.30 Deletion and Tombstones

Tombstones MAY preserve accountability without preserving deleted sensitive content.

### Requirements

- **PRV-11.30.1** Tombstones MUST NOT contain deleted raw biometrics or documents.
- **PRV-11.30.2** Tombstones MUST NOT contain deleted secrets.
- **PRV-11.30.3** Tombstones MUST retain only accountability/lifecycle information.
- **PRV-11.30.4** Auditability MUST NOT retain deleted content.
- **PRV-11.30.5** Tombstone retention MUST have separate governance.

## 11.31 Data Subject Rights

Where applicable, PaxLI MUST support technical capabilities for authorized access, correction, export, objection, restriction, deletion, and other applicable rights.

### Requirements

- **PRV-11.31.1** Data-subject operations MUST require identity and authorization controls.
- **PRV-11.31.2** Requests MUST NOT expose another person's data.
- **PRV-11.31.3** Rights operations MUST be auditable.
- **PRV-11.31.4** Rights processing MUST account for tenant controller/responsibility roles.
- **PRV-11.31.5** Legal exceptions MUST be governed rather than silently ignored.

## 11.32 Access and Export

Data export is controlled.

### Requirements

- **PRV-11.32.1** Export MUST require explicit authorization.
- **PRV-11.32.2** Export scope MUST be explicit.
- **PRV-11.32.3** Export MUST respect tenant boundaries.
- **PRV-11.32.4** Highly sensitive export MUST require stronger controls.
- **PRV-11.32.5** Export MUST be auditable.
- **PRV-11.32.6** Export artifacts MUST have retention and deletion controls.

## 11.33 Correction and Rectification

Correction MUST preserve historical integrity.

### Requirements

- **PRV-11.33.1** Historical audit records MUST NOT be silently rewritten.
- **PRV-11.33.2** Corrected attributes MUST have traceable provenance where required.
- **PRV-11.33.3** Correction MUST NOT alter historical decisions without governed re-verification.
- **PRV-11.33.4** Affected derived records MUST have propagation semantics.

## 11.34 Restriction and Objection

Processing restriction or objection may block new processing or secondary use while preserving required audit/security operations.

### Requirements

- **PRV-11.34.1** Restriction MUST be distinct from deletion.
- **PRV-11.34.2** Restricted data MUST NOT be used for newly prohibited purposes.
- **PRV-11.34.3** Required security and audit controls MUST remain operational.
- **PRV-11.34.4** Restriction behavior MUST be auditable.

## 11.35 Erasure Interaction

Erasure interacts with evidence, decisions, audit, and retention.

### Requirements

- **PRV-11.35.1** Erasure MUST NOT automatically delete legally or operationally required audit records.
- **PRV-11.35.2** Retained accountability records MUST minimize personal content.
- **PRV-11.35.3** Erasure MUST NOT fabricate historical states.
- **PRV-11.35.4** The relationship between erased evidence and retained provenance MUST be explicit.
- **PRV-11.35.5** Lawful deletion that prevents full reconstruction MUST preserve remaining provenance without recreating deleted content.

## 11.36 Cross-Border and Third-Party Processing

Cross-border and third-party processing must follow applicable jurisdictional governance.

### Requirements

- **PRV-11.36.1** External processing locations MUST be identifiable where required.
- **PRV-11.36.2** Third-party processing MUST have authorized purpose.
- **PRV-11.36.3** Sensitive data MUST NOT transfer to unapproved providers.
- **PRV-11.36.4** Cross-border requirements MUST be evaluated before activation.
- **PRV-11.36.5** Material provider changes MUST trigger privacy review.

## 11.37 External Providers

External providers are controlled data processors or service dependencies under applicable governance.

### Requirements

- **PRV-11.37.1** Provider data flows MUST be documented.
- **PRV-11.37.2** Provider responses MUST NOT automatically become unrestricted records.
- **PRV-11.37.3** Provider-returned sensitive data MUST receive PaxLI classification.
- **PRV-11.37.4** Provider access MUST use controlled credentials.
- **PRV-11.37.5** Provider failure MUST NOT cause unnecessary disclosure or duplication.
- **PRV-11.37.6** Provider retention MUST be understood where applicable.

## 11.38 Data Breach and Privacy Incidents

Privacy incidents include unauthorized access, disclosure, alteration, destruction, loss, cross-tenant exposure, processing, or retention.

### Requirements

- **PRV-11.38.1** Incidents MUST be detectable where reasonably possible.
- **PRV-11.38.2** Material incidents MUST be recorded.
- **PRV-11.38.3** Incident records MUST minimize additional exposure.
- **PRV-11.38.4** Response MUST integrate with Part VII security handling.
- **PRV-11.38.5** Applicable notification obligations MUST be evaluated.
- **PRV-11.38.6** Containment MUST prioritize preventing additional exposure.

## 11.39 Privacy Logging and Auditability

Privacy-sensitive operations must be auditable without logging sensitive content.

### Requirements

- **PRV-11.39.1** Required highly sensitive access MUST be auditable.
- **PRV-11.39.2** Deletion MUST be auditable.
- **PRV-11.39.3** Export MUST be auditable.
- **PRV-11.39.4** Administrative privacy operations MUST be auditable.
- **PRV-11.39.5** Audit events MUST NOT contain unnecessary sensitive payloads.

## 11.40 Privacy-Preserving Observability

Observability is operational visibility, not a secondary sensitive-data repository.

### Requirements

- **PRV-11.40.1** Logs MUST NOT contain raw biometric data.
- **PRV-11.40.2** Logs MUST NOT contain raw identity-document content.
- **PRV-11.40.3** Logs MUST NOT contain authentication secrets.
- **PRV-11.40.4** Logs MUST NOT contain full identity numbers unless explicitly justified and protected.
- **PRV-11.40.5** Exception messages MUST be sanitized.
- **PRV-11.40.6** Traces MUST receive appropriate privacy classification.
- **PRV-11.40.7** Production debug logging MUST NOT disable privacy controls.

## 11.41 Data Disclosure

Disclosure outside the originating tenant or authorized boundary requires explicit authorization.

### Requirements

- **PRV-11.41.1** Recipients MUST be identifiable where required.
- **PRV-11.41.2** Scope MUST be explicit.
- **PRV-11.41.3** Disclosure MUST be auditable where required.
- **PRV-11.41.4** Sensitive disclosure MUST use protected transport.
- **PRV-11.41.5** Technical retrievability MUST NOT alone authorize disclosure.

## 11.42 Analytics and Secondary Use

Operational analytics remain purpose-limited.

### Requirements

- **PRV-11.42.1** Analytics MUST use minimum necessary data.
- **PRV-11.42.2** Analytics datasets MUST NOT automatically receive unrestricted production evidence access.
- **PRV-11.42.3** Materially different secondary use MUST undergo governance.
- **PRV-11.42.4** Raw biometrics and documents MUST NOT be used for general analytics by default.
- **PRV-11.42.5** Aggregation MUST NOT be assumed anonymous solely because fields were removed.

## 11.43 Model Training and Research

Production verification data MUST NOT automatically become a training dataset. Secondary use requires explicit purpose, approval, privacy assessment, minimization/de-identification where appropriate, and an authorized dataset boundary.

### Requirements

- **PRV-11.43.1** Production data MUST NOT be used for training by technical default.
- **PRV-11.43.2** Secondary model-development use MUST have explicit authorized purpose.
- **PRV-11.43.3** Training datasets MUST have documented provenance.
- **PRV-11.43.4** Dataset construction MUST apply minimization.
- **PRV-11.43.5** Highly sensitive research data MUST have appropriate access controls.
- **PRV-11.43.6** Research datasets MUST NOT inherit production tenant access.
- **PRV-11.43.7** Dataset exports MUST be governed.
- **PRV-11.43.8** Training use MUST consider legal, contractual, consent, and governance requirements.
- **PRV-11.43.9** Evaluation datasets MUST be distinguishable from operational datasets.
- **PRV-11.43.10** Dataset lineage MUST identify source and governance.
- **PRV-11.43.11** Source data MUST have explicit authorization for the intended research or training purpose before entering a derived dataset.
- **PRV-11.43.12** Derived datasets, model artifacts, and evaluation artifacts MUST have retention, deletion, and source-governance semantics.
- **PRV-11.43.13** Source deletion or restriction MUST trigger an assessed propagation action for derived datasets and model artifacts where technically and legally applicable.

## 11.44 Synthetic and Derived Data

Synthetic data may reduce exposure; derived data is not automatically non-personal.

### Requirements

- **PRV-11.44.1** Synthetic datasets MUST be distinguishable from real production data.
- **PRV-11.44.2** Synthetic data MUST NOT contain unintended real-person information.
- **PRV-11.44.3** Derived representations MUST be classified by residual identity risk.
- **PRV-11.44.4** De-identification MUST be evaluated by actual re-identification risk.
- **PRV-11.44.5** Removing names MUST NOT imply biometric anonymity.

## 11.45 Data Quality and Integrity

Privacy protection requires correct subject, tenant, purpose, and provenance association.

### Requirements

- **PRV-11.45.1** Data MUST retain sensitivity-appropriate integrity protection.
- **PRV-11.45.2** Processing errors MUST NOT reassign data across tenants.
- **PRV-11.45.3** Corrupted sensitive data MUST NOT silently become trusted evidence.
- **PRV-11.45.4** Integrity failures MUST be observable.
- **PRV-11.45.5** Recovery MUST preserve provenance.

## 11.46 Privacy Failure Semantics

Privacy failures include encryption, authorization-context, deletion, retention, tenant-isolation, provider-disclosure, and audit failures.

### Requirements

- **PRV-11.46.1** Privacy-control failure MUST fail safely.
- **PRV-11.46.2** Failure MUST NOT downgrade highly sensitive data protection.
- **PRV-11.46.3** Failure MUST NOT produce a false deletion claim.
- **PRV-11.46.4** Tenant-isolation failure MUST be a security/privacy incident.
- **PRV-11.46.5** Privacy-control failure that prevents valid deterministic evaluation MUST produce final `INCONCLUSIVE`, not `VERIFIED` or `REJECTED` merely because processing stopped.
- **PRV-11.46.6** Privacy failure MUST remain distinct from verification outcome.

## 11.47 Privacy vs Verification Semantics

Privacy state and verification state are distinct. Deletion or historical unavailability does not itself imply verification failure.

### Requirements

- **PRV-11.47.1** Privacy controls MUST NOT declare verdicts.
- **PRV-11.47.2** Data unavailability MUST remain distinct from evidence failure.
- **PRV-11.47.3** Privacy interruption MUST use safe outcome semantics.
- **PRV-11.47.4** The Decision Engine remains sole final-verdict authority.
- **PRV-11.47.5** Privacy policy MUST NOT override Decision Engine authority.

## 11.48 Privacy and Decision Authority

Privacy components may restrict access, prevent processing, require deletion, block disclosure, enforce retention, or report privacy failures. They MUST NOT independently declare final outcomes.

### Requirements

- **PRV-11.48.1** No privacy component may declare a final verification verdict.
- **PRV-11.48.2** Privacy enforcement MUST preserve Decision Engine boundaries.
- **PRV-11.48.3** Privacy restrictions MUST be system conditions, not fabricated evidence.
- **PRV-11.48.4** Historical decision provenance MUST remain distinct from privacy lifecycle state.

## 11.49 Data Protection Impact Assessment

Material high-risk processing requires impact assessment. Triggers include biometrics, large-scale verification, 1:N search, new providers, new secondary use, cross-border processing, automated decision changes, and large migrations.

### Requirements

- **PRV-11.49.1** Material changes MUST be identified before activation.
- **PRV-11.49.2** Assessments MUST identify affected data categories.
- **PRV-11.49.3** Assessments MUST consider security, privacy, reliability, and misuse risk.
- **PRV-11.49.4** Mitigations MUST be tracked to implementation or governance decisions.
- **PRV-11.49.5** Unresolved material privacy risks MUST block ordinary activation unless governed exception permits release.

## 11.50 Privacy by Design

Privacy requirements influence architecture before implementation.

### Requirements

- **PRV-11.50.1** New sensitive flows MUST undergo privacy review.
- **PRV-11.50.2** New storage locations MUST have classification and retention semantics.
- **PRV-11.50.3** New sensitive APIs MUST undergo privacy review.
- **PRV-11.50.4** Privacy MUST be included in architecture decisions.
- **PRV-11.50.5** Controls MUST NOT rely solely on developer discipline.

## 11.51 Privacy Configuration

Privacy-sensitive configuration includes retention, export permissions, evidence storage, logging sensitivity, provider sharing, and secondary-use policy.

### Requirements

- **PRV-11.51.1** Privacy configuration MUST be validated.
- **PRV-11.51.2** Invalid critical privacy configuration MUST fail closed.
- **PRV-11.51.3** Material changes MUST be auditable.
- **PRV-11.51.4** Configuration MUST have version/change provenance where required.
- **PRV-11.51.5** Configuration MUST NOT permit prohibited processing.

## 11.52 Tenant-Configurable Privacy Controls

Tenant settings MAY exist but remain bounded by platform controls.

### Requirements

- **PRV-11.52.1** Tenants MUST NOT disable mandatory platform privacy controls.
- **PRV-11.52.2** Tenant configuration MUST remain tenant-scoped.
- **PRV-11.52.3** Tenant privacy settings MUST be auditable.
- **PRV-11.52.4** Tenant settings MUST NOT permit cross-tenant access.
- **PRV-11.52.5** Tenant settings MUST NOT bypass statutory or platform controls.

## 11.53 Data Residency

PaxLI supports explicit data-residency identification.

### Requirements

- **PRV-11.53.1** Production data locations MUST be identifiable.
- **PRV-11.53.2** Residency constraints MUST be represented in deployment architecture.
- **PRV-11.53.3** Backups and replicas MUST be included in residency analysis.
- **PRV-11.53.4** Provider locations MUST be considered where relevant.
- **PRV-11.53.5** Residency changes MUST undergo governance review.

## 11.54 Backup and Disaster Recovery

Backups are copies of production data and receive source-classification protection.

### Requirements

- **PRV-11.54.1** Sensitive backups MUST receive source-equivalent protection.
- **PRV-11.54.2** Backup access MUST be restricted.
- **PRV-11.54.3** Backup retention MUST be governed.
- **PRV-11.54.4** Backup locations MUST be included in residency analysis.
- **PRV-11.54.5** Restoration MUST preserve tenant boundaries.
- **PRV-11.54.6** Backup procedures MUST be tested.

## 11.55 Data Restoration

Restoration preserves classification and privacy semantics.

### Requirements

- **PRV-11.55.1** Restored data MUST retain classification.
- **PRV-11.55.2** Restored data MUST retain tenant association.
- **PRV-11.55.3** Restoration MUST NOT bypass deletion or retention governance.
- **PRV-11.55.4** Deleted data MUST NOT be resurrected without explicit recovery semantics.
- **PRV-11.55.5** Restoration MUST be auditable.
- **PRV-11.55.6** Post-restoration integrity and access controls MUST be verified.

## 11.56 Data Lifecycle

The lifecycle is:

```text
COLLECT -> CLASSIFY -> PROCESS -> STORE / DERIVE -> USE
        -> RETAIN -> EXPIRE -> DELETE / DISPOSE
```

### Requirements

- **PRV-11.56.1** Each material category MUST have a lifecycle.
- **PRV-11.56.2** Lifecycle transitions MUST have defined authority.
- **PRV-11.56.3** Lifecycle failures MUST be observable.
- **PRV-11.56.4** Lifecycle operations MUST preserve provenance where required.
- **PRV-11.56.5** Data MUST NOT remain indefinitely in undefined lifecycle state.

## 11.57 Data Migration

Migration preserves tenant association, classification, provenance, retention, deletion state, and integrity.

### Requirements

- **PRV-11.57.1** Migration MUST have defined source and destination.
- **PRV-11.57.2** Migration MUST preserve tenant isolation.
- **PRV-11.57.3** Migration MUST preserve retention metadata.
- **PRV-11.57.4** Migration MUST preserve deletion/tombstone semantics where applicable.
- **PRV-11.57.5** Migration MUST NOT create uncontrolled duplicate copies.
- **PRV-11.57.6** Migration MUST be auditable.

## 11.58 Data Portability

Portability produces usable data without unnecessary exposure.

### Requirements

- **PRV-11.58.1** Portable representations MUST identify scope.
- **PRV-11.58.2** Exports MUST preserve necessary provenance.
- **PRV-11.58.3** Export formats MUST NOT include secrets.
- **PRV-11.58.4** Highly sensitive exports MUST have explicit access controls.
- **PRV-11.58.5** Exported artifacts MUST have defined retention.

## 11.59 Data Disposal Verification

Disposal states are `REQUESTED`, `INITIATED`, `COMPLETED`, `PARTIALLY_COMPLETED`, and `FAILED`.

### Requirements

- **PRV-11.59.1** Successful deletion MUST NOT be reported before required work completes.
- **PRV-11.59.2** Partial deletion MUST be explicit.
- **PRV-11.59.3** Failed disposal MUST be observable.
- **PRV-11.59.4** Verification MUST account for governed secondary stores.
- **PRV-11.59.5** Disposal records MUST NOT reproduce disposed content.

## 11.60 Privacy Testing

Privacy testing includes unit, integration, contract, security, negative, failure, isolation, deletion, retention, logging, and export tests.

### Requirements

- **PRV-11.60.1** Every material privacy requirement MUST have a verification method.
- **PRV-11.60.2** Privacy tests MUST include prohibited behavior.
- **PRV-11.60.3** Privacy tests MUST include failure paths.
- **PRV-11.60.4** Privacy tests MUST include cross-tenant attempts.
- **PRV-11.60.5** Privacy tests MUST include leakage attempts.
- **PRV-11.60.6** Privacy tests MUST be included in Part VIII reporting.

## 11.61 Adversarial Privacy Testing

Adversarial testing includes manipulated tenant identifiers, ID guessing, enumeration, malformed export/deletion, log injection, error extraction, timing discovery, cross-tenant access, and replayed administrative requests.

### Requirements

- **PRV-11.61.1** Unauthorized sensitive-data access MUST fail closed.
- **PRV-11.61.2** Cross-tenant enumeration MUST be tested.
- **PRV-11.61.3** Errors MUST NOT reveal unnecessary sensitive information.
- **PRV-11.61.4** Privacy controls MUST be tested under malformed/adversarial input.
- **PRV-11.61.5** Privacy regression tests MUST be maintained after material changes.

## 11.62 Privacy Conformance

Privacy conformance follows Part VIII at normative requirement level.

### Requirements

- **PRV-11.62.1** Each `PRV-*` requirement MUST trace to implementation and verification evidence.
- **PRV-11.62.2** Passing tests alone MUST NOT establish complete privacy conformance.
- **PRV-11.62.3** Privacy nonconformance MUST be classified.
- **PRV-11.62.4** Material privacy nonconformance MUST affect release conformance.
- **PRV-11.62.5** Approved exceptions MUST NOT be requirement-level conformance.
- **PRV-11.62.6** Privacy conformance MUST be included in release reporting.

## 11.63 Regulatory and Jurisdictional Extension

Jurisdictional extensions may add consent, retention, residency, rights, transfer, biometrics, automated decision, breach, or sector controls.

### Requirements

- **PRV-11.63.1** Extensions MUST be explicitly identified.
- **PRV-11.63.2** Extensions MUST NOT silently override constitutional invariants.
- **PRV-11.63.3** Extensions MUST be versioned or traceable.
- **PRV-11.63.4** Jurisdiction behavior MUST be testable.
- **PRV-11.63.5** Extensions MUST NOT become globally applicable without governance.

## 11.64 Deferred Privacy Capabilities

Advanced analytics privacy, subject-request orchestration, cryptographic deletion proofs, consent integrations, privacy-preserving computation, and jurisdictional automation MAY be deferred under Part IX.

### Requirements

- **PRV-11.64.1** Deferred privacy capabilities MUST NOT be represented as active.
- **PRV-11.64.2** Deferral MUST NOT weaken active v1.0 privacy requirements.
- **PRV-11.64.3** Activation MUST use Part IX governance.
- **PRV-11.64.4** Activation MUST include applicable security, privacy, reliability, and conformance review.
- **PRV-11.64.5** Deferral MUST NOT bypass current requirements.

## 11.65 Privacy Exceptions and Governance

Privacy exceptions are explicit and governed.

### Requirements

- **PRV-11.65.1** Exceptions MUST have unique identifiers.
- **PRV-11.65.2** Exceptions MUST be recorded in the governed registry.
- **PRV-11.65.3** Exceptions MUST have explicit scope.
- **PRV-11.65.4** Exceptions MUST have compensating controls where applicable.
- **PRV-11.65.5** Exceptions MUST have review or expiration semantics.
- **PRV-11.65.6** Approved exceptions MUST NOT change nonconformant requirement status to conformant.
- **PRV-11.65.7** Exceptions MUST NOT authorize prohibited processing without legal and governance authority.

## 11.66 Privacy Incident Escalation

Privacy incidents integrate with security and reliability incident management.

### Requirements

- **PRV-11.66.1** Material incidents MUST have escalation paths.
- **PRV-11.66.2** Cross-tenant exposure MUST receive highest-priority treatment.
- **PRV-11.66.3** Credential compromise affecting sensitive data MUST be security and privacy risk.
- **PRV-11.66.4** Incident records MUST preserve chronology.
- **PRV-11.66.5** Response MUST prevent further exposure where possible.
- **PRV-11.66.6** Regulatory and contractual response MUST be evaluated.

## 11.67 Production Privacy Readiness

Production privacy readiness requires classification, access control, isolation, retention, deletion, audit, logging hygiene, backup protection, provider governance, incident handling, and conformance evidence.

### Requirements

- **PRV-11.67.1** Privacy readiness MUST be assessed before release.
- **PRV-11.67.2** Critical privacy controls MUST have objective evidence.
- **PRV-11.67.3** Privacy failure scenarios MUST be tested.
- **PRV-11.67.4** Sensitive-leakage tests MUST pass.
- **PRV-11.67.5** Tenant-isolation tests MUST pass.
- **PRV-11.67.6** Retention/deletion controls MUST have verified behavior.
- **PRV-11.67.7** Production observability MUST avoid sensitive-data leakage.
- **PRV-11.67.8** Privacy readiness MUST be part of release conformance.

## 11.68 Normative Data Protection Model

```text
Data Subject -> Collection -> Classification -> Authorized Purpose
             -> Processing -> Evidence / Derived Data -> Decision Engine
             -> Durable Result -> Audit / Lifecycle -> Retain -> Expire -> Delete
```

The model preserves:

```text
Data != Evidence
Evidence != Decision
Decision != Audit Record
Audit Record != Raw Evidence
Authorization != Legal Basis
Retention != Permanent Storage
Deletion Request != Deletion Completion
Derived Data != Automatically Anonymous
System Failure != Verification Rejection
```

### Requirements

- **PRV-11.68.1** Every sensitive flow MUST have an identifiable lifecycle.
- **PRV-11.68.2** Evidence MUST remain distinguishable from final decision.
- **PRV-11.68.3** Decisions MUST remain attributable to authorized Decision Engine execution.
- **PRV-11.68.4** Auditability MUST avoid unnecessary sensitive-content replication.
- **PRV-11.68.5** Data protection MUST remain enforceable during failure and recovery.
- **PRV-11.68.6** Tenant boundaries MUST apply throughout.
- **PRV-11.68.7** Secondary use MUST require explicit governance.
- **PRV-11.68.8** Lifecycle completion MUST be verifiable.
- **PRV-11.68.9** Privacy semantics MUST remain compatible with Part II.

## 11.69 Constitutional Principle

PaxLI treats personal, identity, biometric, document, and verification data as controlled assets rather than unrestricted application state. It MUST know what data it possesses, why it possesses it, how sensitive it is, who may access it, which tenant owns the context, how it was produced, how long it may be retained, where it is stored, when it must be deleted, what derived information exists, what external parties received it, and what governance permits its use.

Privacy MUST NOT sacrifice reliability, auditability, or verification correctness. Security MUST NOT justify indefinite retention. Auditability MUST NOT justify raw sensitive evidence. Analytics and machine-learning improvement MUST NOT become automatic secondary-use licenses. Deletion MUST NOT be falsely reported while governed copies remain. Privacy controls MUST NOT become alternate decision authority.

> **PaxLI MUST collect only what it is authorized to process, use it only for governed purposes, protect it according to sensitivity, preserve only what is justified, expose only what is authorized, and dispose of it when its governed lifecycle ends—while preserving evidence integrity, auditability, reliability, and exclusive Decision Engine authority.**

## End of Part XI
