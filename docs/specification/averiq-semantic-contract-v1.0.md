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
| III | Evidence Semantics | Planned |
| IV | Verification Workflow | Planned |
| V | Decision Engine | Planned |
| VI | API Contract | Planned |
| VII | Security and Governance | Planned |
| VIII | Conformance | Planned |
| IX | Deferred Architecture | Planned |

## Current normative artifact

[Part II - Architectural Invariants](part-02-architectural-invariants.md) establishes the architectural constitution for v1.0. It defines twelve stable invariants covering verdict authority, safe decision failure, evidence semantics, durable results, webhook independence, evidence integrity, policy immutability, tenant isolation, credential separation, bounded policy evaluation, result accessibility, and audit completeness.

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
