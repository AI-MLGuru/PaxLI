# Averiq by PaxAlpha

# Decision & Verification Semantics Specification

## Part VI - API Contract

**Semantic Contract:** v1.0  
**Document Status:** Normative  
**Product:** Averiq by PaxAlpha  
**Positioning:** Identity Verification & Biometric Trust Infrastructure  
**Tagline:** Verify with confidence.

## 6.0 Purpose and Scope

This part defines the normative external API contract for Averiq. The API is the boundary through which authorized clients create verification sessions, submit evidence, retrieve workflow state and results, receive completion notifications, and administer tenant-scoped configuration.

This part defines resource semantics, authentication and authorization, tenant isolation, request and response contracts, versioning, idempotency, concurrency, errors, HTTP status semantics, rate limiting, retry behavior, webhooks, Management API boundaries, pagination, privacy, observability, and compatibility. It does not prescribe a programming language, framework, database, queue, proxy, or deployment platform.

### Requirements

- **API-6.0.1** The API MUST be consistent with Parts II-V.
- **API-6.0.2** The API MUST NOT introduce contradictory session, evidence, workflow, decision, security, reliability, or privacy semantics.
- **API-6.0.3** Undefined API behavior MUST defer to higher-priority semantic and architectural rules.

## 6.1 API Design Principles

The API is designed around explicit state, deterministic semantics, tenant isolation, least privilege, safe failure, idempotent retry, durable results, privacy by design, stable machine-readable errors, and backwards-compatible evolution.

### Requirements

- **API-6.1.1** Successful evidence submission MUST NOT mean successful verification.
- **API-6.1.2** Internal implementation details MUST NOT become normative public semantics.
- **API-6.1.3** Workflow state, processing state, evidence state, and final decision MUST remain distinct.
- **API-6.1.4** Equivalent authorized requests against equivalent persisted state MUST behave deterministically.

## 6.2 API Versioning

Averiq uses explicit major versions. The initial public API is `/v1/`.

### Requirements

- **API-6.2.1** Every versioned endpoint MUST belong to an explicit API version.
- **API-6.2.2** Breaking changes MUST NOT occur within a major version.
- **API-6.2.3** Non-breaking additions MUST NOT alter existing field, state, error-code, or operation meaning.
- **API-6.2.4** Materially incompatible changes MUST use a new major version.
- **API-6.2.5** API versioning MUST NOT change the meaning of historical results.

## 6.3 Tenant and Authentication Context

Tenant context is derived from authenticated credentials and authorization context. A client-supplied tenant identifier in a header, query, or body is never authoritative by itself.

### Requirements

- **API-6.3.1** Every tenant-owned operation MUST resolve tenant identity from authenticated authorization context.
- **API-6.3.2** A client MUST NOT override its effective tenant with an arbitrary identifier.
- **API-6.3.3** Resource access MUST be authorized against the authenticated tenant.
- **API-6.3.4** Cross-tenant access MUST NOT disclose protected existence or contents.
- **API-6.3.5** Credentials MUST NOT authorize operations beyond granted permissions.
- **API-6.3.6** Authentication and authorization failures MUST NOT expose secrets or sensitive security state.

## 6.4 Verification API vs Management API

The Verification API operates verification sessions under `/v1/verification-sessions/...`. The Management API administers policies, credentials, webhooks, tenant configuration, audit access, and privileged operational configuration under `/v1/management/...`.

### Requirements

- **API-6.4.1** Verification and Management APIs MUST remain logically separated.
- **API-6.4.2** Ordinary verification credentials MUST NOT implicitly authorize management operations.
- **API-6.4.3** Management credentials MUST use distinct elevated authorization controls.
- **API-6.4.4** Rate limits MAY differ between API planes.
- **API-6.4.5** Management audit requirements MUST be at least as strong as equivalent privileged operations.

## 6.5 Resource Model

Core public resources are Verification Session, Evidence, Verification Result, Policy, Credential, Webhook Configuration, and Audit Event. Public resources represent durable domain objects, not internal implementation objects.

### Requirements

- **API-6.5.1** Public resources MUST have stable identifiers.
- **API-6.5.2** Identifiers MUST NOT encode sensitive identity information.
- **API-6.5.3** Representations MUST expose only fields authorized for the principal.
- **API-6.5.4** Database IDs, storage paths, worker IDs, topology, and secrets MUST NOT be mandatory public fields.

## 6.6 Verification Session Resource

A session is a bounded workflow distinct from evidence, processing execution, and final decision.

```json
{
  "id": "vs_...",
  "status": "PROCESSING",
  "decision": null,
  "created_at": "...",
  "submitted_at": "...",
  "completed_at": null,
  "expires_at": "...",
  "policy": {"id": "policy_...", "version": "..."}
}
```

### Requirements

- **API-6.6.1** A session MUST have a stable public identifier.
- **API-6.6.2** `status` MUST represent workflow lifecycle semantics.
- **API-6.6.3** Final outcome MUST be represented separately from lifecycle status.
- **API-6.6.4** `VERIFIED`, `REJECTED`, `REVIEW_REQUIRED`, and `INCONCLUSIVE` MUST NOT be session lifecycle states.
- **API-6.6.5** Authorized clients MUST receive the final decision for completed sessions.

## 6.7 Session Creation

Representative operation: `POST /v1/verification-sessions`. The request may specify authorized purpose, policy, expiration, permitted evidence types, and client reference.

### Requirements

- **API-6.7.1** Creation MUST authenticate and authorize the principal.
- **API-6.7.2** The session MUST belong to the authenticated tenant.
- **API-6.7.3** Clients MUST NOT create sessions under another tenant.
- **API-6.7.4** Creation MUST assign a unique session identifier.
- **API-6.7.5** Creation MUST NOT imply successful verification.
- **API-6.7.6** Invalid or unauthorized policy/configuration MUST fail deterministically without creating an ambiguously configured session.

## 6.8 Evidence Submission

Representative operations include `POST /v1/verification-sessions/{id}/selfie`, `/document`, and `/liveness` where activated. Submission is acceptance into the workflow, not a decision.

### Requirements

- **API-6.8.1** Submission MUST authorize both tenant and target session.
- **API-6.8.2** Accepted evidence MUST NOT imply a final decision.
- **API-6.8.3** Submission MUST preserve Part III evidence semantics.
- **API-6.8.4** Invalid request, rejected submission, accepted evidence, processing failure, and verification failure MUST be distinguishable.
- **API-6.8.5** Raw model outputs MUST NOT be exposed as final verdicts.
- **API-6.8.6** Submission MUST enforce size, type, format, authorization, and security constraints.

## 6.9 Evidence Retrieval

Authorized clients may retrieve evidence metadata where permitted. Raw biometric and document content has stricter access controls.

### Requirements

- **API-6.9.1** Retrieval MUST enforce tenant and authorization boundaries.
- **API-6.9.2** Metadata and content MUST follow their respective classifications.
- **API-6.9.3** Highly sensitive content MUST NOT be returned without explicit authorization.
- **API-6.9.4** Images, embeddings, credentials, and equivalent content MUST NOT appear in ordinary errors.
- **API-6.9.5** Deleted or expired evidence MUST NOT be represented as retrievable.
- **API-6.9.6** Lawfully deleted evidence MAY expose only permitted deletion state or metadata.

## 6.10 Verification Result Retrieval

Representative operation: `GET /v1/verification-sessions/{id}`. A result is durable only after persistence under Parts IV and V.

### Requirements

- **API-6.10.1** Results MUST NOT be exposed as durable before persistence.
- **API-6.10.2** Persisted results MUST be retrievable independently of webhook delivery.
- **API-6.10.3** `VERIFIED` MUST correspond to a valid authorized Decision Engine result.
- **API-6.10.4** Infrastructure failure MUST NOT be represented as `REJECTED` merely because processing failed.
- **API-6.10.5** Unsafe completion MUST expose `INCONCLUSIVE` or another explicitly authorized outcome.

## 6.11 Processing Representation

Public processing MAY expose `QUEUED`, `PROCESSING`, and `COMPLETED`. Retry counters, circuit state, worker assignment, and infrastructure recovery remain internal unless explicitly contracted.

### Requirements

- **API-6.11.1** Internal processing details MUST NOT be required public semantics.
- **API-6.11.2** Processing state MUST remain distinct from final decision.
- **API-6.11.3** Clients MUST NOT infer `REJECTED` from processing failure.
- **API-6.11.4** Clients MUST NOT infer `VERIFIED` from successful processing alone.

## 6.12 Idempotency

Idempotency keys are scoped to authenticated tenant, operation, endpoint, and request semantics.

### Requirements

- **API-6.12.1** Equivalent reuse MUST resolve to the original operation result.
- **API-6.12.2** Materially different reuse MUST produce stable `IDEMPOTENCY_KEY_REUSED`.
- **API-6.12.3** Idempotency records MUST survive the documented retention window.
- **API-6.12.4** Retention/expiration behavior MUST be documented.
- **API-6.12.5** Idempotency MUST NOT permit cross-tenant reuse.
- **API-6.12.6** A failed infrastructure operation MUST NOT become successful solely because a key was supplied.

## 6.13 Concurrent Requests

Concurrent requests may result from retries, duplicated networks, or parallel clients.

### Requirements

- **API-6.13.1** Concurrent requests MUST produce deterministic resource state.
- **API-6.13.2** Races MUST NOT produce contradictory lifecycle states.
- **API-6.13.3** Concurrent submissions MUST be accepted or rejected by deterministic session semantics.
- **API-6.13.4** Cancellation and processing races MUST follow Part IV transitions.
- **API-6.13.5** Races MUST NOT expose unauthorized durable intermediate results.

## 6.14 Request IDs and Correlation

Every request receives or propagates a request identifier; absent identifiers are generated by Averiq.

### Requirements

- **API-6.14.1** Every response MUST contain a request identifier.
- **API-6.14.2** Request IDs MUST support correlation across logs, audits, traces, and diagnostics.
- **API-6.14.3** Request IDs MUST NOT contain sensitive identity information.
- **API-6.14.4** Request IDs MUST NOT authenticate requests.
- **API-6.14.5** Correlation metadata MUST follow privacy and logging restrictions.

## 6.15 Success Envelope

A conceptual success representation is:

```json
{"data": {}, "request_id": "req_..."}
```

### Requirements

- **API-6.15.1** Success responses MUST be machine-readable.
- **API-6.15.2** Success responses MUST NOT expose secrets or unauthorized data.
- **API-6.15.3** Resource data and request metadata MUST be distinguishable.
- **API-6.15.4** HTTP success MUST NOT imply verification success unless a valid final `VERIFIED` decision is present.

## 6.16 Error Envelope

The canonical structured error is:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description",
    "category": "CATEGORY",
    "request_id": "req_...",
    "details": {}
  }
}
```

### Requirements

- **API-6.16.1** Structured errors MUST contain stable machine-readable codes.
- **API-6.16.2** Structured errors MUST contain request identifiers.
- **API-6.16.3** Messages MUST be safe for their intended audience.
- **API-6.16.4** Errors MUST NOT contain keys, tokens, private keys, passwords, biometric content, images, unnecessary identity numbers, stack traces, or infrastructure secrets.
- **API-6.16.5** `details` MUST NOT be an unrestricted internal-state leak.

## 6.17 Error Categories

Defined categories include `VALIDATION`, `AUTHENTICATION`, `AUTHORIZATION`, `NOT_FOUND`, `CONFLICT`, `RATE_LIMITED`, `PROCESSING`, `DEPENDENCY`, `POLICY`, and `INTERNAL`.

### Requirements

- **API-6.17.1** Every public error MUST have a defined category.
- **API-6.17.2** Categories MUST remain stable within a major version.
- **API-6.17.3** Category MUST NOT replace the stable error code.

## 6.18 Stable Error Codes

Representative stable codes include `INVALID_REQUEST`, `AUTHENTICATION_REQUIRED`, `AUTHENTICATION_FAILED`, `PERMISSION_DENIED`, `RESOURCE_NOT_FOUND`, `SESSION_NOT_FOUND`, `SESSION_NOT_ACTIVE`, `INVALID_EVIDENCE`, `EVIDENCE_NOT_ALLOWED`, `POLICY_INVALID`, `POLICY_NOT_FOUND`, `IDEMPOTENCY_KEY_REUSED`, `RATE_LIMITED`, `PROCESSING_UNAVAILABLE`, `EXTERNAL_PROVIDER_UNAVAILABLE`, `EXTERNAL_PROVIDER_TIMEOUT`, and `DECISION_ENGINE_ERROR`.

### Requirements

- **API-6.18.1** Public error codes MUST be stable within a major version.
- **API-6.18.2** Codes MUST NOT silently change meaning.
- **API-6.18.3** Internal exception names MUST NOT become public error codes.
- **API-6.18.4** New codes MAY be added when clients safely handle unknown codes.
- **API-6.18.5** Clients MUST distinguish retryable conditions from client-correction conditions.

## 6.19 HTTP Status Semantics

| Status | Meaning |
|---|---|
| `200` | Successful retrieval or operation |
| `201` | Resource created |
| `202` | Accepted for asynchronous processing |
| `204` | Successful operation without body |
| `400` | Invalid request |
| `401` | Authentication required or failed |
| `403` | Authenticated but unauthorized |
| `404` | Unavailable to the authorized principal |
| `409` | Resource or operation conflict |
| `422` | Semantically invalid request |
| `429` | Rate limited |
| `500` | Unexpected internal error |
| `502` | Upstream dependency failure |
| `503` | Temporarily unavailable |
| `504` | Gateway or dependency timeout |

### Requirements

- **API-6.19.1** Status codes MUST follow documented semantics.
- **API-6.19.2** A successfully processed `REJECTED` verification MUST NOT automatically be an HTTP error.
- **API-6.19.3** Infrastructure failure MUST NOT be represented as successful `REJECTED` verification.
- **API-6.19.4** `202` MAY represent accepted incomplete processing.
- **API-6.19.5** `429` MUST include rate-limit semantics.

## 6.20 Validation Errors

Validation covers malformed JSON, unsupported content, missing or invalid fields, invalid identifiers, unsupported evidence, invalid policy references, and invalid idempotency use.

### Requirements

- **API-6.20.1** Invalid requests MUST fail deterministically.
- **API-6.20.2** Validation errors MUST NOT initiate processing.
- **API-6.20.3** Responses SHOULD identify safe affected fields or constraints.
- **API-6.20.4** Error details MUST NOT unnecessarily echo sensitive values.

## 6.21 Authentication Errors

Authentication errors include missing, invalid, expired, revoked, or unsupported credentials.

### Requirements

- **API-6.21.1** Authentication failures MUST NOT disclose other credentials, tenants, or privileged resources.
- **API-6.21.2** Authentication responses MUST NOT expose secrets or verification material.
- **API-6.21.3** Credential lifecycle semantics MUST conform to Part VII.

## 6.22 Authorization Errors

Authorization evaluates principal, tenant, credential, permission, resource, and operation.

### Requirements

- **API-6.22.1** Authentication MUST NOT imply unrestricted authorization.
- **API-6.22.2** Authorization MUST evaluate principal, tenant, credential, permission, resource, and operation.
- **API-6.22.3** Alternate endpoint representations MUST NOT bypass authorization.
- **API-6.22.4** Authorization failures MUST NOT disclose unnecessary cross-tenant information.

## 6.23 Rate Limiting

Rate limits MAY apply at tenant, credential, endpoint, operation, network-source, or Management API principal scope.

### Requirements

- **API-6.23.1** Rate-limit rejection MUST return `429`.
- **API-6.23.2** Rate-limited responses MUST contain a stable code.
- **API-6.23.3** Responses MUST include `Retry-After` where applicable.
- **API-6.23.4** Responses SHOULD support responsible retry without exposing limiter internals.
- **API-6.23.5** Rate limiting MUST preserve tenant isolation.
- **API-6.23.6** Rate limiting MUST NOT turn a valid outcome into `REJECTED`.

## 6.24 Retry Semantics

Clients may retry network failures, timeouts, `429`, transient `5xx`, and documented dependency failures. Retries MUST respect idempotency.

### Requirements

- **API-6.24.1** An unsuccessful response MUST NOT prove that no side effect occurred.
- **API-6.24.2** Clients SHOULD use idempotency keys for duplicate-side-effect operations.
- **API-6.24.3** Retryable conditions MUST be distinguishable from client-correction conditions.
- **API-6.24.4** Internal retries MUST be bounded under Part X.
- **API-6.24.5** Client retries MUST NOT create duplicate durable results.
- **API-6.24.6** Retries MUST NOT bypass authorization, rate limits, expiration, or lifecycle rules.

## 6.25 Webhooks

Webhooks notify authorized tenants about durable verification events. They are not the source of truth.

Initial event types MAY include `verification.completed`, `verification.failed`, and `verification.review_required`.

### Requirements

- **API-6.25.1** Webhooks MUST NOT emit before referenced result/event persistence.
- **API-6.25.2** Delivery failure MUST NOT alter the verification result.
- **API-6.25.3** Tenants MUST recover authoritative results through the Verification API.
- **API-6.25.4** Payloads MUST identify referenced event/resource without unnecessary sensitive data.
- **API-6.25.5** Event semantics MUST match the underlying result.
- **API-6.25.6** Webhooks MUST NOT declare a result differing from the persisted Decision Engine result.

## 6.26 Webhook Event Identity

```json
{"id": "evt_...", "type": "verification.completed", "version": "1", "created_at": "...", "data": {}}
```

### Requirements

- **API-6.26.1** Events MUST have globally unique IDs in the applicable event namespace.
- **API-6.26.2** IDs MUST remain stable across retries.
- **API-6.26.3** Retries MUST NOT create new event IDs.
- **API-6.26.4** Payloads MUST include explicit event version.
- **API-6.26.5** IDs MUST support client deduplication.

## 6.27 Webhook Delivery Semantics

Conceptual delivery lifecycle:

```text
PERSISTED -> DELIVERY_PENDING -> DELIVERING -> DELIVERED
                                  |
                                  v
                         DELIVERY_FAILED -> RETRY -> DEAD_LETTERED
```

### Requirements

- **API-6.27.1** Delivery MUST occur only after durable result/event persistence.
- **API-6.27.2** Delivery failure MUST NOT modify the decision.
- **API-6.27.3** Retries MUST preserve the original event ID.
- **API-6.27.4** Retry behavior MUST be bounded by retry and retention policies.
- **API-6.27.5** Permanent delivery failure MUST NOT prevent polling retrieval.
- **API-6.27.6** Delivery attempts MUST be auditable.
- **API-6.27.7** Delivery status MUST NOT prevent authorized result retrieval.

## 6.28 Webhook Security

Webhook endpoints are tenant-controlled external trust boundaries.

### Requirements

- **API-6.28.1** Payloads MUST be authenticated or cryptographically verifiable.
- **API-6.28.2** Authentication MUST support secret rotation.
- **API-6.28.3** Signing secrets MUST NOT be returned after authorized initial issuance.
- **API-6.28.4** Payloads MUST include timestamp or equivalent replay control.
- **API-6.28.5** Consumers MUST detect replayed events.
- **API-6.28.6** Payloads MUST NOT include unnecessary biometric or document content.
- **API-6.28.7** Configuration changes MUST be authenticated, authorized, and audited.

## 6.29 Management API

Representative Management API resources are `/v1/management/policies`, `/credentials`, `/webhooks`, `/audit-events`, and `/configuration`.

### Requirements

- **API-6.29.1** Management operations MUST require explicit management permissions.
- **API-6.29.2** Management operations MUST remain within authenticated tenant boundaries unless explicitly platform-authorized.
- **API-6.29.3** Policy changes MUST create immutable versions.
- **API-6.29.4** Credential lifecycle operations MUST be auditable.
- **API-6.29.5** Webhook configuration changes MUST be auditable.
- **API-6.29.6** Management operations MUST NOT modify historical verification results.

## 6.30 Management API Security Boundary

Representative operational permissions are `verification:create`, `verification:read`, and `verification:cancel`. Administrative permissions include `policy:manage`, `credential:manage`, `webhook:manage`, `audit:read`, and `configuration:manage`.

### Requirements

- **API-6.30.1** Administrative permissions MUST NOT be implicit for operational credentials.
- **API-6.30.2** Credential management MUST require explicit authorization.
- **API-6.30.3** Policy management MUST require explicit authorization.
- **API-6.30.4** Audit access MUST require explicit authorization.
- **API-6.30.5** Management API tenant isolation MUST be at least as strong as Verification API isolation.

## 6.31 Pagination and Listing

List endpoints MAY provide cursor pagination.

```json
{"data": [], "pagination": {"next_cursor": "...", "has_more": true}, "request_id": "req_..."}
```

### Requirements

- **API-6.31.1** Pagination MUST be deterministic.
- **API-6.31.2** Cursors MUST NOT grant cross-tenant access.
- **API-6.31.3** Cursors MUST NOT contain raw sensitive information.
- **API-6.31.4** Expired or invalid cursor behavior MUST be defined.
- **API-6.31.5** Unbounded large result sets MUST NOT be returned by default where availability could be threatened.

## 6.32 Filtering and Query Semantics

Supported filters MUST be explicitly documented.

### Requirements

- **API-6.32.1** Filtering MUST remain inside the caller's authorization boundary.
- **API-6.32.2** Filters MUST NOT enable cross-tenant discovery.
- **API-6.32.3** Unsupported filters MUST fail rather than be silently ignored.
- **API-6.32.4** Filtering MUST NOT expose unauthorized fields.
- **API-6.32.5** Query parameters MUST NOT act as authorization controls.

## 6.33 Resource Retention and Deletion Visibility

Resource visibility depends on lifecycle, retention, lawful deletion, authorization, and expiration.

### Requirements

- **API-6.33.1** The API MUST respect evidence and resource retention policies.
- **API-6.33.2** Deleted evidence MUST NOT remain falsely retrievable.
- **API-6.33.3** Deletion MUST NOT silently alter historical decision meaning.
- **API-6.33.4** Audit records MAY remain after evidence deletion while deleted content remains unavailable.
- **API-6.33.5** Safe distinctions among deletion, expiration, authorization, and non-existence MUST follow the public contract.
- **API-6.33.6** Deleted highly sensitive content MUST NOT be exposed through remaining metadata.

## 6.34 API Privacy Boundaries

API responses follow data minimization for identity and biometric information.

### Requirements

- **API-6.34.1** Responses MUST expose only minimum sensitive information required.
- **API-6.34.2** Images, embeddings, credentials, and equivalent content MUST NOT be returned without explicit authorization.
- **API-6.34.3** Sensitive identity values MUST NOT be unnecessarily echoed in validation errors.
- **API-6.34.4** Errors MUST NOT expose raw model input or inference artifacts.
- **API-6.34.5** Logs MUST NOT automatically mirror complete sensitive request bodies.
- **API-6.34.6** Public representations MUST follow Part XI privacy rules.
- **API-6.34.7** Privacy controls MUST be enforced server-side.

## 6.35 API Observability

Useful correlation includes request ID, authorized tenant context, session ID, operation, HTTP status, latency, error code, and processing stage where permitted.

### Requirements

- **API-6.35.1** Every request MUST be observable through a correlation identifier.
- **API-6.35.2** Failures MUST have stable codes or operational categories.
- **API-6.35.3** Observability MUST NOT require raw identity or biometric data.
- **API-6.35.4** The API MUST support latency, error, rate-limit, dependency, and processing-failure measurement.
- **API-6.35.5** Observability failure MUST NOT block safe processing unless observability is itself a required safety control.
- **API-6.35.6** Monitoring SHOULD detect reliability degradation before unobserved customer-facing failure where feasible.

## 6.36 Deprecation and Compatibility

A deprecated endpoint, field, parameter, response field, or webhook version MUST be explicitly identified.

### Requirements

- **API-6.36.1** Deprecated functionality MUST be identified.
- **API-6.36.2** Deprecation documentation MUST provide migration guidance where needed.
- **API-6.36.3** Planned removal MUST communicate a sunset date where applicable.
- **API-6.36.4** Breaking changes MUST NOT occur silently within a major version.
- **API-6.36.5** Historical responses and persisted results MUST remain semantically reconstructible.
- **API-6.36.6** Compatibility MUST be checked against contract tests before release.
- **API-6.36.7** No universal minimum deprecation period is promised unless separately governed.

## 6.37 Conformance Requirements

API conformance covers authentication, authorization, tenant isolation, resources, lifecycle, evidence, decisions, idempotency, concurrency, errors, HTTP statuses, rate limits, retries, webhooks, Management API boundaries, pagination, privacy, observability, and compatibility.

Suggested structure:

```text
tests/contracts/api/
|- test_authentication.py
|- test_authorization.py
|- test_tenant_isolation.py
|- test_sessions.py
|- test_evidence.py
|- test_results.py
|- test_idempotency.py
|- test_concurrency.py
|- test_errors.py
|- test_rate_limits.py
|- test_webhooks.py
|- test_management_api.py
|- test_privacy.py
`- test_compatibility.py
```

### Requirements

- **API-6.37.1** Every normative API requirement MUST map to a conformance test or explicitly documented deferred test.
- **API-6.37.2** Contract tests MUST cover success and failure behavior.
- **API-6.37.3** Tests MUST include cross-tenant access, credential misuse, malformed requests, replay, duplicates, concurrency, invalid idempotency, rate exhaustion, webhook failure, dependency failure, deleted evidence, and unauthorized sensitive access.
- **API-6.37.4** Tests MUST prove infrastructure failure is not surfaced as verification rejection.
- **API-6.37.5** Tests MUST prove webhook failure does not prevent result retrieval.
- **API-6.37.6** Tests MUST prove `VERIFIED` corresponds to a durably persisted Decision Engine result.
- **API-6.37.7** Tests MUST prove public errors contain no prohibited secrets or highly sensitive information.
- **API-6.37.8** Conformance MUST be reported at normative-requirement level, not only endpoint level.

## 6.38 Constitutional Principle

The API is the externally observable boundary of Averiq's trust model. It MUST preserve these distinctions:

> **A request is not evidence. Evidence is not a decision. Processing is not verification. Notification is not persistence. Authentication is not authorization. Infrastructure failure is not verification rejection.**

The API MUST expose only decisions that are authorized, semantically valid, durably recorded, tenant-isolated, and consistent with the evidence, policy, workflow, security, reliability, and privacy contracts.

## End of Part VI
