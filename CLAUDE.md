# CLAUDE.md

## Averiq by PaxAlpha

**Product:** Averiq by PaxAlpha  
**Positioning:** Identity Verification & Biometric Trust Infrastructure  
**Tagline:** Verify with confidence.

Averiq is a production-oriented, auditable, explainable, tenant-isolated identity verification platform. It must fail safely under uncertainty and infrastructure failure.

## Source Of Truth

The normative architectural source of truth is:

```text
docs/specification/averiq-semantic-contract-v1.0.md
```

Read the relevant specification part before changing architecture or semantics. Current normative parts are:

```text
docs/specification/
├── part-02-architectural-invariants.md
├── part-03-evidence-semantics.md
├── part-04-verification-workflow.md
├── part-05-decision-engine.md
├── part-06-api-contract.md
├── part-07-security-and-governance.md
├── part-08-conformance.md
├── part-09-deferred-architecture.md
├── part-10-reliability-and-operations.md
└── part-11-data-protection-and-privacy.md
```

The README may retain historical scaffold wording such as `FOUNDATION-001`; use the current specification and Git history as the authoritative project baseline.

Do not silently weaken or redefine the specification in implementation. If code and specification conflict:

1. identify the exact conflicting requirement;
2. inspect the relevant implementation and tests;
3. preserve the normative semantics;
4. surface the conflict instead of choosing silently;
5. change the specification only through an intentional architectural decision.

## Constitutional Rules

### Decision authority

Models and components produce evidence. Policies define how evidence is interpreted. The Decision Engine alone produces final verification outcomes:

```text
VERIFIED
REJECTED
REVIEW_REQUIRED
INCONCLUSIVE
```

No model, OCR engine, document validator, liveness component, provider adapter, API route, repository, retry system, circuit breaker, security component, privacy component, audit service, worker, or webhook may independently declare a final verdict.

`VERIFIED` requires explicit evaluation of the applicable immutable policy. Policy evaluation must not be bypassed because evidence appears strong.

### Safe failure

Technical, dependency, security, privacy, or operational failure is not identity failure. When a valid deterministic decision cannot be established, the safe final outcome MUST be `INCONCLUSIVE`, never an invented `REJECTED` or `VERIFIED` result.

### State separation

Keep these dimensions separate:

```text
Session lifecycle state
    != Processing execution state
    != Evidence status
    != Final verification decision
```

`NOT_RUN` is an internal execution state, not an evidence status. `COMPLETED` does not imply `VERIFIED`.

### Tenant isolation

Tenant identity comes from trusted authentication and authorization context, never from an arbitrary client header, query parameter, or body field.

```text
Authenticated Principal
        -> AuthorizationContext
        -> trusted tenant_id
        -> tenant-scoped operation
```

Every tenant-owned resource lookup must enforce tenant scope and fail closed without revealing protected cross-tenant resource existence. This applies to sessions, evidence, decisions, policies, credentials, audit, storage, caches, background processing, and administrative resources. Cross-tenant access is a critical failure.

### Audit constitution

For a governed externally observable action:

```text
Action
  -> Required Audit Event
  -> Durable Audit Acceptance
  -> Observable Effect
```

Required audit persistence failure must block the governed effect and remain distinct from verification failure; it must never fabricate `REJECTED`. Audit scope includes successful and materially failed verification, governance, authorization, security, privacy, lifecycle, and materially significant internal actions. Required audit events must be durable, integrity-protected, actor/system-attributed, tenant-attributed, correlated, retry-safe, stable in identity, immutable in history, and classified as transaction-critical or best-effort. Audit records are not evidence and never make decisions. Do not put raw credentials, secrets, biometric data, identity documents, or unnecessary sensitive payloads in audit events.

### Privacy and data protection

Every important data element needs a classification, purpose and lawful-processing context, access boundary, retention/deletion rule, lifecycle, residency/backup treatment, and protection requirement. Sensitive access must fail closed when authorization context is unavailable.

```text
PUBLIC
INTERNAL
SENSITIVE
HIGHLY_SENSITIVE
```

Treat names and identity metadata as sensitive. Treat documents, selfies, liveness media, embeddings, credentials, tokens, private keys, and secrets as highly sensitive. Never leak them through logs, exceptions, API errors, traces, audit records, or debug output. Protect primary data, backups, replicas, and secondary stores. Enforce retention and deletion rather than merely recording policy. Production verification data does not automatically become model-training data.

### Reliability

Reliability means correctness, safety, recoverability, observability, auditability, and availability. Use bounded timeouts, bounded retries, idempotency, controlled degradation, dependency health, and recovery verification. Do not trade authorization, privacy, evidence integrity, audit ordering, or Decision Engine authority for availability.

### Deferred architecture

`PLANNED`, `DEFERRED`, `EXPERIMENTAL`, `CANDIDATE`, and `ACTIVATED` are distinct states. `TARGET` and `FUTURE` capability labels map to governed `DEFERRED` status when outside the active release. Deferred capabilities require an explicit register entry and activation preconditions. Implementation alone cannot activate them. Deferred capabilities, including 1:N biometric search, advanced liveness, durable queue infrastructure, advanced human review, session resumption, and expanded providers, must not weaken active v1.0 requirements or appear as active functionality without governed activation. `REVIEW_REQUIRED` does not imply that a human-review subsystem exists.

## Foundation 006 Focus

Foundation 006 is the current security and data-protection implementation focus. Before changing it, inspect the relevant Part VII, Part XI, and Part VIII requirements plus existing code and tests.

Relevant areas include:

```text
core/security/
infrastructure/security/
infrastructure/database/
apps/api/averiq_api/
tests/security/
tests/adversarial/
tests/integration/
tests/unit/
```

Preserve the existing direction:

- credential issuance, hashing, verification, rotation, expiry, and revocation;
- principal-derived tenant authorization;
- no trust in arbitrary `X-Tenant-ID`;
- tenant-scoped session, evidence, and audit access;
- sensitive-data classification and recursive sanitization;
- generic authentication failures;
- operational versus administrative privilege separation.

Do not restart completed foundations or introduce new infrastructure without a current specification requirement.

## Workflow For Changes

Before editing:

1. Inspect the relevant specification requirements.
2. Inspect the owning domain/application abstraction.
3. Inspect nearby infrastructure and call sites.
4. Inspect existing tests and failure behavior.
5. State one concrete hypothesis and one focused check.
6. Make the smallest coherent change.

After editing:

1. Run the cheapest focused test or executable check first.
2. Repair the same slice if it fails.
3. Run broader tests when the change crosses boundaries.
4. Run Ruff, mypy, compile checks, or the project-equivalent validation.
5. Inspect the diff and check for accidental files.
6. Report changed files, validation run, failures, and known gaps honestly.

Do not claim a test passed unless fresh output proves it. Do not hide pre-existing failures; distinguish them from regressions introduced by the current change.

## Testing And Conformance

Conformance is requirement-level, not just test-suite-level:

```text
Normative requirement
        -> Implementation
        -> Verification method
        -> Evidence
        -> Conformance status
        -> Release decision
```

Use the repository's existing test layers:

```text
tests/unit/
tests/integration/
tests/security/
tests/adversarial/
tests/performance/
tests/benchmarks/
tests/contracts/       # required for normative contracts where practical
```

Test both positive and negative behavior. For security, privacy, reliability, and authority requirements, include adversarial and failure-path tests. Important cases include cross-tenant access, malformed credentials, revoked credentials, replay, duplicate requests, persistence failure, dependency outage, timeout, retry exhaustion, audit failure, sensitive-data leakage, and Decision Engine safe failure.

## Code And Dependency Discipline

Prefer existing repository patterns and capability-oriented interfaces. Keep infrastructure behind abstractions such as evidence storage, inference runtime, provider, notification, cache, and key-provider capabilities.

Before adding a dependency or service, establish that it is required by the specification and that existing dependencies cannot satisfy the need. Do not add Redis, Kafka, vector databases, workflow engines, queues, or model infrastructure merely because they are conventional.

Database and storage changes must consider tenant constraints, idempotency, concurrency, transactions, checksums, deletion, retention, auditability, rollback, and partial failure.

## API Rules

Keep the Verification API and Management API logically separate:

```text
/v1/verification-sessions/...
/v1/management/...
```

Preserve stable request IDs, error codes, categories, HTTP semantics, idempotency, tenant authorization, privacy-minimized responses, durable result retrieval, and webhook independence. A successful submission is not a successful verification. Webhooks notify; polling retrieves the authoritative durable result.

## Git And Repository Hygiene

Before committing:

```bash
git status
git diff --check
git diff
```

Prefer explicit staging over blind `git add .` when unrelated or untracked files may exist. Do not commit automatically unless explicitly requested.

Inspect suspicious files before deleting them. Previous terminal artifacts have appeared in repository history; do not remove unusual files without confirming they are accidental and unreferenced. Never commit secrets, shell fragments, editor artifacts, temporary files, or generated junk.

## Priority When Requirements Conflict

Use this order:

```text
Architectural Invariants
        -> Semantic Definitions
        -> API Contract
        -> Domain/Application Rules
        -> Infrastructure Implementation
        -> Operational Convenience
```

If two normative requirements conflict, identify both, trace their dependency, and surface the conflict for deliberate resolution. Never resolve a constitutional conflict through a silent implementation shortcut.

## Current Objective

The specification constitution is complete. The implementation objective is to finish Foundation 006 and then perform a requirement-level conformance pass across the foundations before adding deferred capabilities or production features.

The goal is not merely that the application runs. The goal is that it behaves correctly under normal operation, failure, attack, retries, concurrency, dependency outage, privacy constraints, and operational stress.

## Final Principles

- Evidence is not a verdict.
- Models produce evidence; the Decision Engine makes decisions.
- Only the Decision Engine owns final verification outcomes.
- Technical failure must not become rejection.
- `INCONCLUSIVE` is a legitimate safety outcome.
- Tenant identity from the client is never authoritative.
- Required audit precedes a governed observable effect.
- Audit infrastructure records decisions but never makes them.
- Sensitive data must not leak through logs, errors, or ordinary audit records.
- Production data is not automatically training data.
- Deferred architecture cannot weaken active guarantees.
- Passing tests alone does not establish conformance.
- Exceptions must be explicit, numbered, approved, scoped, risk-assessed, time-bounded or reviewable, recorded in Appendix A, and governed. An approved exception may permit a governed release but does not make the affected requirement conformant.
- Reliability means correctness under failure, not merely uptime.

When uncertain, ask whether the change makes Averiq more reliable, secure, explainable, auditable, privacy-preserving, and correct under failure.
