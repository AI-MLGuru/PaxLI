# PaxLI by PaxAlpha

# Decision & Verification Semantics Specification

## Part X - Reliability and Operations

**Semantic Contract:** v1.0  
**Document Status:** Normative  
**Requirement Prefix:** `REL-*`  
**Product:** PaxLI by PaxAlpha

## 10.0 Purpose and Scope

This part defines the normative reliability and operational requirements for PaxLI. Reliability encompasses availability, correctness, controlled degradation, predictable failure, recoverability, observability, operational safety, dependency resilience, capacity, incident response, disaster recovery, and recovery verification.

PaxLI MUST distinguish verification failure, infrastructure failure, dependency failure, operational failure, security failure, data-protection failure, and inconclusive outcome. Infrastructure failure MUST NOT automatically become verification rejection.

### Requirements

- **REL-10.0.1** Reliability MUST be treated as a system property.
- **REL-10.0.2** Operational behavior MUST preserve Parts II-IX.
- **REL-10.0.3** Infrastructure failure MUST NOT automatically produce `REJECTED`.
- **REL-10.0.4** Reliability failures MUST have explicit observable semantics.

## 10.1 Reliability Principles

PaxLI reliability follows fail safely, fail predictably, recover deterministically, preserve evidence integrity and decision authority, avoid cascades, detect degradation early, prefer controlled degradation, preserve tenant isolation and auditability, expose operational state, and verify recovery.

### Requirements

- **REL-10.1.1** Reliability mechanisms MUST preserve Decision Engine authority.
- **REL-10.1.2** Reliability mechanisms MUST NOT silently alter historical decisions.
- **REL-10.1.3** Reliability mechanisms MUST preserve tenant boundaries.
- **REL-10.1.4** Reliability mechanisms MUST distinguish unavailable processing from failed identity verification.

## 10.2 Reliability Model

Reliability is assessed across:

```text
Availability | Correctness | Resilience | Recoverability | Observability
```

### Requirements

- **REL-10.2.1** Production reliability assessment MUST consider all five dimensions.

## 10.3 Reliability Boundaries

```text
Client -> API -> Workflow/Session -> Processing Orchestration
                                  |-> Evidence Storage
                                  |-> Inference Runtime
                                  |-> External Providers
                                  |-> Supporting Infrastructure
                                  -> Decision Engine -> Durable Result
```

Failure in one component MUST NOT automatically become semantic failure in another.

### Requirements

- **REL-10.3.1** Component failures MUST remain attributable to the affected component.
- **REL-10.3.2** Reliability mechanisms MUST distinguish component state from verification state.

## 10.4 Service Level Indicators

PaxLI SHOULD measure API availability and errors, completion and latency, evidence upload, Decision Engine and dependency latency/availability, storage/database health, webhook delivery, recovery time, retries, timeouts, circuit activation, `INCONCLUSIVE` rate, `REVIEW_REQUIRED` rate, and infrastructure-induced inconclusive rate.

### Requirements

- **REL-10.4.1** Critical SLIs MUST be measurable.
- **REL-10.4.2** SLIs MUST distinguish customer-visible failures from internal events.
- **REL-10.4.3** Metrics MUST NOT require highly sensitive evidence content.

## 10.5 Service Level Objectives

SLOs SHOULD be defined for production-critical availability, latency, completion, dependencies, evidence storage, result retrieval, webhooks, and recovery. Claims MUST be based on system requirements and evidence.

### Requirements

- **REL-10.5.1** Published SLOs MUST be measurable.
- **REL-10.5.2** SLOs MUST define measurement windows.
- **REL-10.5.3** SLO breaches MUST be detectable.
- **REL-10.5.4** SLOs MUST NOT be represented as guarantees without supporting capability.

## 10.6 Availability Semantics

Availability is evaluated separately for API, evidence, processing, decision, result retrieval, and webhook functions. Webhook unavailability MUST NOT make persisted results unavailable.

### Requirements

- **REL-10.6.1** Result retrieval MUST remain independent of webhook delivery.
- **REL-10.6.2** Webhook failure MUST NOT erase or invalidate persisted results.
- **REL-10.6.3** Availability measurements MUST identify affected capability.

## 10.7 Latency Semantics

PaxLI distinguishes request, processing, dependency, inference, decision, persistence, and notification latency. End-to-end latency is not equivalent to any individual component latency.

### Requirements

- **REL-10.7.1** Critical latency measurements MUST include correlation identifiers.
- **REL-10.7.2** Dependency latency MUST be attributable where practical.
- **REL-10.7.3** Excessive latency MUST trigger controlled timeout or degradation.

## 10.8 Timeout Requirements

Every externally dependent or blocking operation MUST have an explicit timeout. A timeout MUST NOT leave an operation indefinitely unresolved.

### Requirements

- **REL-10.8.1** Critical external operations MUST be timeout-bounded.
- **REL-10.8.2** Timeout behavior MUST be deterministic.
- **REL-10.8.3** Timeout MUST NOT automatically produce `REJECTED`.
- **REL-10.8.4** Permitted timeout retries MUST preserve idempotency.

## 10.9 Retry Semantics

Retries MAY recover transient failures but MUST be bounded, policy-controlled, timeout-aware, idempotent for mutations, observable, and appropriate to failure class. Retries MUST NOT amplify outages.

### Requirements

- **REL-10.9.1** Retry policies MUST define maximum attempts.
- **REL-10.9.2** Retry policies MUST define failure classes.
- **REL-10.9.3** Retries SHOULD use exponential backoff and jitter where appropriate.
- **REL-10.9.4** Non-retryable failures MUST NOT be repeatedly retried.
- **REL-10.9.5** Retries MUST NOT create duplicate authoritative evidence or decisions.

## 10.10 Circuit Breaker Semantics

Circuit breakers MAY transition through `CLOSED`, `OPEN`, and `HALF_OPEN`. Circuit state is operational state, never a verification verdict.

### Requirements

- **REL-10.10.1** Circuit breakers MUST prevent uncontrolled repeated dependency calls.
- **REL-10.10.2** Circuit state MUST be observable.
- **REL-10.10.3** Activation MUST produce controlled failure semantics.
- **REL-10.10.4** Recovery MUST require evidence of dependency health.

## 10.11 Dependency Health

Critical dependencies include database, storage, cache where used, inference runtime, identity providers, notification systems, and key management. Health states are `Healthy`, `Degraded`, `Unavailable`, and `Unknown`.

### Requirements

- **REL-10.11.1** Critical dependency health MUST be observable.
- **REL-10.11.2** Health MUST NOT be inferred solely from process existence.
- **REL-10.11.3** Health checks MUST avoid harmful load.

## 10.12 Readiness and Liveness

PaxLI distinguishes liveness, readiness, dependency health, and application correctness. A live process is not necessarily ready; readiness does not imply every dependency can complete verification.

### Requirements

- **REL-10.12.1** Readiness MUST represent safe acceptance of applicable traffic.
- **REL-10.12.2** Liveness MUST detect unrecoverable process failure.
- **REL-10.12.3** Health endpoints MUST NOT expose secrets.

## 10.13 Graceful Degradation

Degradation MAY persist results while webhooks are unavailable, record provider failure, produce safe outcomes when models are unavailable, and continue core verification when non-critical analytics are unavailable. Degradation MUST preserve semantic correctness.

### Requirements

- **REL-10.13.1** Degradation MUST be explicit.
- **REL-10.13.2** Degraded operation MUST NOT produce false evidence.
- **REL-10.13.3** Degradation MUST NOT bypass security controls.
- **REL-10.13.4** Degradation MUST NOT bypass Decision Engine authority.

## 10.14 Safe Failure Semantics

```text
Evidence establishes failure -> possible REJECTED
Infrastructure prevents evaluation -> INCONCLUSIVE
```

Database, runtime, storage, provider, network, overload, and model timeouts are infrastructure conditions unless evidence semantics explicitly establish otherwise. Final outcome remains governed by policy and Decision Engine.

### Requirements

- **REL-10.14.1** Infrastructure failure MUST NOT automatically produce `REJECTED`.
- **REL-10.14.2** Processing failure MUST remain distinct from evidence failure.
- **REL-10.14.3** Safe failure semantics MUST be tested.

## 10.15 Partial Pipeline Failure

Partial success MUST preserve completed evidence without implying complete verification. The Decision Engine receives resulting evidence and availability semantics.

### Requirements

- **REL-10.15.1** Partial failure MUST preserve completed evidence.
- **REL-10.15.2** Failed components MUST NOT erase valid historical evidence.
- **REL-10.15.3** The Decision Engine MUST determine the final outcome.

## 10.16 Overload and Backpressure

Protection MAY include rate limits, concurrency limits, bounded workers, admission control, queue limits, circuit breakers, quotas, and load shedding. Load shedding MUST be controlled and observable.

### Requirements

- **REL-10.16.1** Critical resources MUST have capacity boundaries.
- **REL-10.16.2** Overload MUST NOT cause uncontrolled exhaustion.
- **REL-10.16.3** Load shedding MUST NOT corrupt persisted state.

## 10.17 Concurrency

Concurrent uploads, completion, cancellation, expiration, result retrieval, and webhook processing MUST be deterministic.

### Requirements

- **REL-10.17.1** Concurrent operations MUST preserve state-machine validity.
- **REL-10.17.2** Concurrent mutations MUST NOT create contradictory authoritative states.
- **REL-10.17.3** Races MUST be reliability-tested.

## 10.18 Crash Recovery

Recovery from process failure MUST consider incomplete requests, processing, evidence, decisions, retries, locks, idempotency, and audit.

### Requirements

- **REL-10.18.1** Crashes MUST NOT silently create contradictory decisions.
- **REL-10.18.2** Persisted evidence MUST remain recoverable under retention policy.
- **REL-10.18.3** Recovery MUST be deterministic when inputs and policy are unchanged.

## 10.19 Database Failure

Database failures include connection, timeout, transaction, constraint, deadlock, pool, availability, and replication failures.

### Requirements

- **REL-10.19.1** Database failures MUST be observable.
- **REL-10.19.2** Database failures MUST NOT cause silent data loss.
- **REL-10.19.3** Retriable database failures MUST be bounded.
- **REL-10.19.4** Failed transactions MUST preserve integrity.

## 10.20 Evidence Storage Failure

If evidence content cannot be durably stored, persistence MUST NOT be reported as successful. Metadata/object inconsistency MUST be safely reconciled or explicitly marked.

### Requirements

- **REL-10.20.1** Evidence success MUST wait for required durability.
- **REL-10.20.2** Partial storage failures MUST be recoverable or explicitly marked.
- **REL-10.20.3** Recovery MUST preserve integrity references.

## 10.21 Inference Runtime Failure

Inference failures include loading, crash, memory, unsupported input, timeout, malformed output, and incompatibility. Runtime failure is not identity rejection.

### Requirements

- **REL-10.21.1** Inference failure MUST be represented as processing failure or inconclusive evidence as applicable and MUST produce final `INCONCLUSIVE` when it prevents a valid deterministic decision.
- **REL-10.21.2** Invalid model output MUST NOT become valid evidence.
- **REL-10.21.3** Runtime failure MUST be observable.

## 10.22 External Provider Failure

Providers are unreliable dependencies. Timeout, outage, rate limiting, malformed/incomplete/schema-changed/conflicting responses, and elevated latency MUST be handled explicitly. Provider failure is not mismatch.

### Requirements

- **REL-10.22.1** Provider failures MUST be classified.
- **REL-10.22.2** Responses MUST be validated before becoming evidence.
- **REL-10.22.3** Unavailability MUST remain distinct from mismatch.

## 10.23 Webhook Reliability

Webhook delivery is asynchronous notification, not source of truth. It requires retry, backoff, stable identity, replay protection, observability, and failure tracking.

### Requirements

- **REL-10.23.1** Results MUST be persisted independently of webhooks.
- **REL-10.23.2** Retries MUST NOT create duplicate authoritative decisions.
- **REL-10.23.3** Delivery failure MUST be observable.

## 10.24 Observability

Operational observability includes logs, metrics, traces, audit events, health signals, and dependency signals, distinct from sensitive evidence.

### Requirements

- **REL-10.24.1** Critical production paths MUST be observable.
- **REL-10.24.2** Observability MUST support request correlation.
- **REL-10.24.3** Observability MUST NOT require raw biometric or document content.

## 10.25 Structured Logging

Structured logs SHOULD include request/correlation ID, permitted tenant/session IDs, stage, operation, duration, status, code, dependency, model, and policy versions. Logs MUST NOT contain identity numbers, images, embeddings, tokens, keys, passwords, or secrets.

### Requirements

- **REL-10.25.1** Sensitive data MUST NOT be logged by default.
- **REL-10.25.2** Logging controls MUST be tested.
- **REL-10.25.3** Error logging MUST preserve diagnostic usefulness without protected data.

## 10.26 Metrics Integrity

Metrics MUST distinguish provider timeout from identity mismatch, inference failure from face mismatch, and webhook failure from verification failure.

### Requirements

- **REL-10.26.1** Metrics MUST distinguish semantic failure classes.
- **REL-10.26.2** Dashboards MUST NOT collapse infrastructure failure into identity rejection.
- **REL-10.26.3** Metric definitions MUST be documented.

## 10.27 Alerting

Alerts SHOULD cover SLO breach, latency, database/storage/inference/provider failure, timeout/retry anomalies, circuit activation, exhaustion, abnormal inconclusive rate, and security-relevant operational anomalies.

### Requirements

- **REL-10.27.1** Critical failures MUST generate observable signals.
- **REL-10.27.2** Alerts SHOULD identify affected components.
- **REL-10.27.3** Alert thresholds MUST be reviewable.

## 10.28 Reliability Baselines

Baselines SHOULD cover latency, errors, provider behavior, inference, inconclusive rate, utilization, and throughput. Baselines enable degradation detection before outage.

### Requirements

- **REL-10.28.1** Material degradation SHOULD be detectable before complete failure where practical.
- **REL-10.28.2** Baselines MUST be based on observed behavior.

## 10.29 Capacity Management

Capacity limits include CPU, memory, disk, database connections, storage, network, workers, concurrency, and provider quotas.

### Requirements

- **REL-10.29.1** Critical capacity constraints MUST be documented.
- **REL-10.29.2** Exhaustion MUST have controlled behavior.
- **REL-10.29.3** Capacity limits MUST NOT cause silent corruption.

## 10.30 Resource Exhaustion

PaxLI MUST protect against memory, disk, connection, worker, request, storage, and payload exhaustion.

### Requirements

- **REL-10.30.1** Critical resource limits MUST be bounded.
- **REL-10.30.2** Exhaustion MUST be observable.
- **REL-10.30.3** Exhaustion MUST produce controlled failure.

## 10.31 Disaster Recovery

Disaster scenarios include database/storage loss, region failure, credential compromise, corrupted deployment, accidental deletion, and catastrophic outage. Recovery prioritizes safety, integrity, isolation, evidence, decision integrity, and restoration.

### Requirements

- **REL-10.31.1** Disaster-recovery procedures MUST be documented before production reliance.
- **REL-10.31.2** Recovery procedures MUST be tested periodically.

## 10.32 Recovery Point Objective

RPO defines acceptable data loss by data category. Highly sensitive evidence and authoritative decisions SHOULD have stricter recovery requirements than telemetry.

### Requirements

- **REL-10.32.1** Production RPOs MUST be defined where applicable.
- **REL-10.32.2** RPO claims MUST match backup and replication capability.

## 10.33 Recovery Time Objective

RTO defines target restoration time for API, evidence, processing, result retrieval, and critical dependencies.

### Requirements

- **REL-10.33.1** Production RTOs MUST be documented where applicable.
- **REL-10.33.2** RTO claims MUST be validated through recovery testing.

## 10.34 Backup Requirements

Critical persistent state SHOULD have appropriate backups, including authoritative database state, decisions, evidence metadata, audit, configuration, policies, and required operational state. Raw evidence backups MUST follow retention, privacy, encryption, and deletion requirements.

### Requirements

- **REL-10.34.1** Critical state MUST have defined recovery mechanisms.
- **REL-10.34.2** Backups MUST follow data classification.
- **REL-10.34.3** Backup restoration MUST be tested.

## 10.35 Restore Verification

Unrestored backups MUST NOT be assumed recoverable. Restore testing SHOULD verify integrity, schema, isolation, evidence references, policy versions, provenance, and compatibility.

### Requirements

- **REL-10.35.1** Critical backups MUST have tested restoration procedures.
- **REL-10.35.2** Restore testing MUST verify semantic integrity, not file existence alone.

## 10.36 Incident Management

Incident response follows:

```text
Detect -> Classify -> Contain -> Investigate -> Recover -> Verify -> Review
```

### Requirements

- **REL-10.36.1** Material incidents MUST have documented response procedures.
- **REL-10.36.2** Incident handling MUST preserve evidence and audit integrity.
- **REL-10.36.3** Security and privacy incidents MUST follow applicable procedures.

## 10.37 Incident Severity

Severity considers outage, partial outage, errors, latency, isolation, evidence, decision, security, and privacy impact. Security/privacy incidents are not ordinary availability incidents merely because service remains operational.

### Requirements

- **REL-10.37.1** Severity MUST consider semantic and security impact.
- **REL-10.37.2** Severity MUST be reassessed as evidence changes.

## 10.38 Incident Containment

Containment may disable dependencies, reduce traffic, disable non-critical features, isolate tenants/components, roll back deployments, rotate credentials, or suspend processing. It MUST preserve authorization and audit.

### Requirements

- **REL-10.38.1** Containment MUST preserve tenant isolation.
- **REL-10.38.2** Containment actions MUST be auditable where applicable.
- **REL-10.38.3** Containment MUST NOT silently alter historical decisions.

## 10.39 Deployment Reliability

Production deployment SHOULD support versioning, health checks, rollback, configuration validation, migration safety, staged rollout, and release observability.

### Requirements

- **REL-10.39.1** Production deployment MUST have a rollback strategy.
- **REL-10.39.2** Deployment failure MUST be detectable.
- **REL-10.39.3** Database migrations MUST have compatibility and recovery considerations.

## 10.40 Rollback

Rollback MUST NOT silently roll back historical decisions. Policy rollback activates an earlier policy while historical decisions retain their original provenance.

### Requirements

- **REL-10.40.1** Rollback MUST preserve historical decision provenance.
- **REL-10.40.2** Rollback MUST NOT silently mutate historical evidence.
- **REL-10.40.3** Critical rollback procedures MUST be tested.

## 10.41 Model Reliability

Model monitoring SHOULD include inference latency/failure, invalid output, distributions, calibration drift, false rejection/acceptance anomalies, and demographic changes. Model degradation is distinct from infrastructure failure.

### Requirements

- **REL-10.41.1** Model runtime failures MUST be observable.
- **REL-10.41.2** Invalid model output MUST NOT enter authoritative decisioning.
- **REL-10.41.3** Material model degradation MUST be detectable.

## 10.42 Decision Engine Reliability

If the Decision Engine cannot safely evaluate:

```text
Decision Engine failure -> no valid final decision -> final INCONCLUSIVE
```

The system MUST NOT manufacture a verdict to satisfy availability.

### Requirements

- **REL-10.42.1** Decision Engine failure MUST produce final `INCONCLUSIVE` with an appropriate stable reason code and MUST NOT produce a fabricated outcome.
- **REL-10.42.2** Decision Engine timeout MUST produce final `INCONCLUSIVE` with an appropriate stable timeout reason code.
- **REL-10.42.3** Decision Engine failures MUST be auditable.
- **REL-10.42.4** Availability objectives MUST NOT override decision correctness.

## 10.43 Reliability and Audit Ordering

Required audit ordering MUST survive failure and retry. For every action governed by a required audit event, the normative order is `Action -> Required Audit Event -> Observable Effect`. The system MUST NOT report success or expose the governed effect when required audit durability failed.

### Requirements

- **REL-10.43.1** Required audit MUST be durably accepted before any governed observable effect.
- **REL-10.43.2** Audit persistence failure MUST have explicit operation semantics.
- **REL-10.43.3** Audit retry MUST preserve event identity.

## 10.44 Reliability and Idempotency

Retries after client, network, process, provider, or database timeouts MUST NOT create duplicate authoritative state.

### Requirements

- **REL-10.44.1** Retried operations MUST preserve idempotency.
- **REL-10.44.2** Idempotency records MUST survive intended duplication-protection failures.

## 10.45 Reliability and Tenant Isolation

Recovery MUST NOT return another tenant's evidence, reuse another tenant's session, expose another tenant's audit, reuse cached identity data, or mix tenant decision context.

### Requirements

- **REL-10.45.1** Recovery paths MUST enforce tenant isolation.
- **REL-10.45.2** Caches and retries MUST be tenant-safe.
- **REL-10.45.3** Disaster recovery MUST preserve ownership.

## 10.46 Reliability Testing

Reliability testing SHOULD include dependency failure, timeouts, exhaustion, circuit breaking, outages, model/provider failure, networks, crashes, resources, concurrency, duplicates, webhook failure, recovery, and rollback.

### Requirements

- **REL-10.46.1** Critical reliability behaviors MUST have automated tests.
- **REL-10.46.2** Failure tests MUST verify semantic outcomes.
- **REL-10.46.3** Recovery tests MUST verify restored correctness.

## 10.47 Fault Injection

Controlled environments MAY inject dependency timeout, refusal, network interruption, process termination, storage/model failure, resource pressure, and malformed responses.

### Requirements

- **REL-10.47.1** Fault injection MUST NOT compromise production data.
- **REL-10.47.2** Scenarios MUST have defined expected behavior.

## 10.48 Chaos and Resilience Testing

Combined-failure testing MAY be introduced with safeguards to verify bounded and understandable propagation.

### Requirements

- **REL-10.48.1** Combined failure testing MUST be controlled and safeguarded.
- **REL-10.48.2** Resilience tests MUST verify controlled propagation.

## 10.49 Operational Readiness

Production readiness includes monitoring, alerts, health, deployment, rollback, failure/recovery procedures, capacity, documentation, ownership, and incident response.

### Requirements

- **REL-10.49.1** Production-critical components MUST have operational ownership.
- **REL-10.49.2** Readiness MUST include failure and recovery assessment.
- **REL-10.49.3** Readiness MUST be demonstrable.

## 10.50 Production Readiness Gate

```text
Correctness + Semantic/Security/Privacy/Reliability Conformance
+ Observability + Recovery Readiness + Ownership -> Production Release
```

### Requirements

- **REL-10.50.1** Production readiness MUST consider reliability evidence.
- **REL-10.50.2** Critical unresolved reliability failures MUST block ordinary release unless governed by Part VIII exception process.
- **REL-10.50.3** Approved exceptions MUST NOT be represented as conformance.

## 10.51 Reliability Conformance

Reliability conformance includes positive recovery and negative behavior such as no infinite retry, duplicate decisions, false rejection, cross-tenant recovery, sensitive logging, silent corruption, or fabricated outcomes.

### Requirements

- **REL-10.51.1** Reliability conformance MUST include negative testing.
- **REL-10.51.2** Reliability conformance MUST include failure-path evidence.
- **REL-10.51.3** Reliability conformance MUST be traceable to individual requirements.

## 10.52 Reliability Evidence

Evidence MAY include automated, load, fault-injection, recovery, restore, monitoring, SLO, incident, deployment, rollback, and dependency-failure results. It MUST identify scenario, environment, version, configuration, time, outcome, and component.

### Requirements

- **REL-10.52.1** Reliability claims MUST have objective evidence.
- **REL-10.52.2** Evidence MUST be attributable to tested system version.

## 10.53 Operational Change Management

Material infrastructure, database, model, policy, dependency, network, security, capacity, and deployment changes require reliability impact assessment.

### Requirements

- **REL-10.53.1** Material reliability changes MUST be reviewable.
- **REL-10.53.2** Changes MUST preserve applicable semantic contracts.

## 10.54 Configuration Reliability

Critical configuration SHOULD be versioned, validated, environment-specific, observable, and auditable. Invalid configuration MUST fail safely.

### Requirements

- **REL-10.54.1** Critical configuration MUST be validated before activation.
- **REL-10.54.2** Invalid critical configuration MUST NOT silently activate unsafe behavior.

## 10.55 Dependency Versioning

Material SDK, runtime, database, operating-system, infrastructure, or API changes require compatibility assessment.

### Requirements

- **REL-10.55.1** Material dependency changes MUST undergo compatibility assessment.
- **REL-10.55.2** Dependency changes MUST NOT silently alter verification semantics.

## 10.56 Reliability and Deferred Architecture

Deferred infrastructure does not mean deferred reliability:

```text
Durable queue deferred != retry semantics deferred
Multi-region deferred != recovery planning deferred
Advanced review deferred != REVIEW_REQUIRED undefined
```

### Requirements

- **REL-10.56.1** Deferred architecture MUST NOT eliminate active v1.0 reliability requirements.
- **REL-10.56.2** Deferred reliability infrastructure activation MUST follow Part IX governance and complete applicable security, privacy, reliability, operational-readiness, and overall conformance assessment.

## 10.57 Reliability and Data Protection

Backups, replication, logs, traces, debugging, recovery, and temporary storage MUST respect classification, retention, deletion, encryption, and privacy requirements. Highly sensitive evidence MUST NOT be retained for convenience.

### Requirements

- **REL-10.57.1** Reliability mechanisms MUST respect data classification.
- **REL-10.57.2** Recovery MUST preserve deletion and retention requirements.

## 10.58 Reliability and Security

Degraded operation MUST NOT disable authentication, authorization, isolation, credential protection, audit, or encryption merely to improve availability.

### Requirements

- **REL-10.58.1** Degraded operation MUST preserve mandatory security.
- **REL-10.58.2** Availability MUST NOT override security boundaries.

## 10.59 Reliability and Decision Correctness

PaxLI prefers controlled `INCONCLUSIVE` over false `REJECTED` or fabricated `VERIFIED` when evaluation is unsafe.

### Requirements

- **REL-10.59.1** Decision correctness MUST take precedence over superficial availability.
- **REL-10.59.2** Infrastructure failure MUST NOT become fabricated identity outcome.

## 10.60 Reliability Degradation Monitoring

PaxLI SHOULD measure infrastructure-induced inconclusive outcomes, processing failures, timeouts, retries, and dependency errors separately from genuine verification failures.

### Requirements

- **REL-10.60.1** Infrastructure-induced degradation SHOULD be measurable.
- **REL-10.60.2** Monitoring SHOULD distinguish infrastructure outcomes from genuine verification failures.

## 10.61 Reliability Review

Reliability review SHOULD examine incidents, near misses, SLOs, dependencies, capacity, failures, recovery, security/privacy events, model behavior, and customer impact.

### Requirements

- **REL-10.61.1** Material incidents MUST inform reliability improvements.
- **REL-10.61.2** Review MUST consider recurring failure patterns.

## 10.62 Operational Documentation

Critical capabilities require documentation of architecture, dependencies, health, failure, recovery, rollback, escalation, ownership, and limitations.

### Requirements

- **REL-10.62.1** Critical procedures MUST be documented.
- **REL-10.62.2** Documentation MUST correspond to actual behavior.

## 10.63 Reliability Ownership

Production-critical components SHOULD have owners responsible for monitoring, incidents, capacity, recovery, dependencies, and improvement.

### Requirements

- **REL-10.63.1** Production-critical components MUST have identifiable operational ownership.

## 10.64 Reliability Review After Change

Material changes affecting availability, latency, failure, recovery, capacity, security, privacy, or decision correctness require reassessment.

### Requirements

- **REL-10.64.1** Material reliability changes MUST be reassessed.
- **REL-10.64.2** Reliability regression SHOULD be detectable before unrestricted rollout.

## 10.65 Reliability Conformance Requirements

### Requirements

- **REL-10.65.1** Critical paths MUST have defined reliability behavior.
- **REL-10.65.2** Critical external operations MUST be timeout-bounded.
- **REL-10.65.3** Retries MUST be bounded.
- **REL-10.65.4** Retries MUST preserve idempotency where applicable.
- **REL-10.65.5** Circuit breakers MUST NOT become verdict authorities.
- **REL-10.65.6** Infrastructure failure MUST NOT automatically produce `REJECTED`.
- **REL-10.65.7** Critical dependencies MUST have observable health.
- **REL-10.65.8** Critical state MUST have recovery mechanisms.
- **REL-10.65.9** Critical backups MUST have tested restoration.
- **REL-10.65.10** Production deployments MUST have rollback procedures.
- **REL-10.65.11** Critical paths MUST have sufficient observability.
- **REL-10.65.12** Sensitive evidence MUST NOT be logged for convenience.
- **REL-10.65.13** Reliability tests MUST include failure paths.
- **REL-10.65.14** Reliability tests MUST include critical recovery.
- **REL-10.65.15** Production readiness MUST include reliability assessment.
- **REL-10.65.16** Reliability mechanisms MUST preserve tenant isolation.
- **REL-10.65.17** Reliability mechanisms MUST preserve evidence integrity.
- **REL-10.65.18** Reliability mechanisms MUST preserve Decision Engine authority.
- **REL-10.65.19** Reliability degradation MUST remain distinct from genuine verification failure.
- **REL-10.65.20** Material reliability claims MUST have objective evidence.
- **REL-10.65.21** Critical changes MUST be reviewable.
- **REL-10.65.22** Degraded operation MUST preserve mandatory security.
- **REL-10.65.23** Degraded operation MUST preserve privacy.
- **REL-10.65.24** Reliability conformance MUST be requirement-traceable.
- **REL-10.65.25** Critical unresolved reliability failures MUST block ordinary release unless governed by approved exception.

## 10.66 Normative Reliability Model

```text
Request -> Valid Path -> Healthy or Degraded
                           |
                 Durable Workflow/Evidence State
                           |
                    Decision Engine
                           |
             Durable Decision Result or Safe INCONCLUSIVE
                           |
                    Observable Result
```

The reliability hierarchy is:

```text
Correctness -> Safety -> Integrity -> Availability -> Convenience
```

Availability MUST NOT override correctness, safety, or integrity.

## 10.67 Relationship to Earlier Parts

Part X operationalizes Parts II-IX. It preserves authority and boundaries, evidence semantics, workflow state, Decision Engine safety, API retry/error/webhook semantics, security during degradation, objective conformance, deferred-architecture boundaries, and applicable Part XI privacy requirements.

### Requirements

- **REL-10.67.1** Reliability behavior MUST remain consistent with all applicable normative Parts.

## 10.68 Constitutional Principle

PaxLI remains trustworthy when parts fail. It prefers known failure over silent corruption, controlled degradation over unbounded failure, `INCONCLUSIVE` over false rejection, durable state over notification, recovery over assumption, and measured reliability over unsupported claims.

The system MUST never manufacture successful verification because infrastructure is unavailable, manufacture rejection because evaluation failed, or sacrifice tenant isolation, evidence integrity, security, privacy, or Decision Engine authority for availability.

## End of Part X
