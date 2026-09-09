# Averiq Decision & Verification Semantics Specification

**Specification version:** Semantic Contract v1.0  
**Product:** Averiq by PaxAlpha  
**Status:** Normative entry point

## Purpose

This document is the canonical entry point for Averiq's Decision & Verification Semantics Specification. The repository is the source of truth for the current approved semantic contract.

The specification defines the behavioral guarantees, security boundaries, evidence semantics, decision rules, API contract, governance requirements, conformance gates, and deferred architecture for Averiq v1.0.

## Parts

| Part | Title | Status |
|---|---|---|
| I | Scope and Governance | Planned |
| II | Architectural Invariants | Normative |
| III | Evidence Semantics | Normative |
| IV | Verification Workflow | Normative |
| V | Decision Engine | Normative |
| VI | API Contract | Normative |
| VII | Security and Governance | Normative |
| VIII | Conformance | Normative |
| IX | Deferred Architecture | Normative |
| X | Reliability & Operations | Normative |
| XI | Data Protection & Privacy | Normative |

## Current normative artifact

[Part II - Architectural Invariants](part-02-architectural-invariants.md) establishes the architectural constitution for v1.0. It defines twelve stable invariants covering verdict authority, safe decision failure, evidence semantics, durable results, webhook independence, evidence integrity, policy immutability, tenant isolation, credential separation, bounded policy evaluation, result accessibility, and audit completeness.

[Part III - Evidence Semantics](part-03-evidence-semantics.md) defines the normative meaning, lifecycle, status and absence semantics, provenance, integrity, immutability, deletion, access boundaries, and Decision Engine contract for evidence.

[Part IV - Verification Workflow](part-04-verification-workflow.md) defines the normative session lifecycle, processing semantics, decision separation, retries, recovery, result persistence, polling, webhooks, audit, and workflow security contract.

[Part V - Decision Engine](part-05-decision-engine.md) defines the normative decision authority, policy evaluation, declarative conditions, gates, rules, safe failure, determinism, provenance, persistence, retrieval, and auditability contract.

[Part VI - API Contract](part-06-api-contract.md) defines the normative external API boundary, resource semantics, authentication and authorization, tenant isolation, errors, idempotency, webhooks, Management API, privacy, observability, and compatibility contract.

[Part VII - Security and Governance](part-07-security-and-governance.md) defines the normative security boundaries, authentication, authorization, tenant isolation, credentials, cryptography, key management, biometric protection, policy governance, incident handling, abuse prevention, security testing, and exceptions contract.

[Part VIII - Conformance](part-08-conformance.md) defines the normative requirement traceability, objective evidence, contract testing, failure and security conformance, release gates, exceptions, deferred requirements, and production-readiness model.

[Part IX - Deferred Architecture](part-09-deferred-architecture.md) defines the normative states, register, activation governance, v1.0 boundaries, future-capability dependencies, and safeguards preventing deferred architecture from weakening the active contract.

[Part X - Reliability & Operations](part-10-reliability-and-operations.md) defines the normative reliability model, timeouts, retries, degradation, dependency health, recovery, incident management, observability, disaster recovery, operational readiness, and production release gates.

[Part XI - Data Protection & Privacy](part-11-data-protection-and-privacy.md) defines the normative data classification, purpose limitation, tenant privacy, access, cryptographic protection, retention, deletion, subject rights, secondary use, jurisdictional extensions, privacy incidents, and production privacy readiness contract.

## Authority and change control

The specification takes precedence over implementation convenience. An implementation MUST NOT silently redefine an established semantic contract. Future parts MUST be checked against Part II before approval. Changes to normative meaning MUST follow the specification governance process and be recorded as approved specification changes.

Architectural discussions, rejected alternatives, and review history are supporting records only. They are not normative unless explicitly promoted into an approved specification artifact.

## Implementation chain

```text
Architectural Invariant
        |
Semantic Specification
        |
Contract Test
        |
Implementation
        |
Conformance Report
        |
Release Gate
```

## v1.0 release rule

A v1.0 release candidate MUST satisfy all applicable normative requirements. A single failed mandatory requirement blocks conformance unless an explicitly approved specification exception applies.
