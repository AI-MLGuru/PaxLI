# PaxLI by PaxAlpha

# Decision & Verification Semantics Specification

## Part IV - Verification Workflow

**Semantic Contract:** v1.0  
**Document Status:** Normative  
**Product:** PaxLI by PaxAlpha  
**Positioning:** Identity Verification & Biometric Trust Infrastructure  
**Tagline:** Verify with confidence.

## 4.0 Purpose and Scope

This part defines the normative workflow semantics governing an PaxLI verification session from creation through evidence submission, processing, decisioning, completion, expiration, cancellation, and result retrieval.

The following concepts are separate and MUST NOT be collapsed into one state machine:

```text
Session Lifecycle State
        !=
Processing Execution State
        !=
Verification Decision
```

The workflow governs session identity and ownership, lifecycle transitions, evidence submission, idempotency, concurrency, processing, retry and recovery, timeout, expiration, cancellation, final decision, result persistence, polling, webhooks, crash recovery, replay handling, audit, and workflow security.

## 4.1 Verification Session Definition

**Status: PREREQUISITE: v1.0**

A verification session is the bounded workflow context for collecting, processing, evaluating, and recording evidence for one verification attempt. A session MUST have a unique identifier, owning tenant, lifecycle state, applicable policy reference, creation timestamp, expiration semantics, evidence relationships, and decision/result state where applicable. A session represents the workflow, not the final identity decision.

### Requirements

- **WF-4.1.1** Every verification attempt MUST occur within an identifiable session.
- **WF-4.1.2** Every session MUST have exactly one owning tenant.
- **WF-4.1.3** Every session MUST have an explicit lifecycle state.
- **WF-4.1.4** A session MUST NOT use `VERIFIED` or `REJECTED` as its lifecycle state.

## 4.2 Session Identity

**Status: PREREQUISITE: v1.0**

Session identity is stable for the lifetime of the session. A session ID MUST NOT be reused for another verification attempt.

### Requirements

- **WF-4.2.1** Every session MUST have a unique identifier.
- **WF-4.2.2** A session identifier MUST remain associated with the same verification attempt throughout its lifecycle.
- **WF-4.2.3** A client MUST NOT select another tenant's session through identifier manipulation.

## 4.3 Session Ownership and Tenant Boundary

**Status: PREREQUISITE: v1.0**

A verification session is tenant-owned. All operations MUST execute within the authenticated tenant's authorization boundary. Tenant identity MUST derive from the authenticated principal as required by Part II Invariant 08.

### Requirements

- **WF-4.3.1** Every session MUST have an explicit tenant association.
- **WF-4.3.2** Session lookup MUST be tenant-scoped.
- **WF-4.3.3** Session mutation MUST be tenant-scoped.
- **WF-4.3.4** Session evidence MUST inherit or explicitly establish the same tenant boundary.
- **WF-4.3.5** A client-supplied tenant identifier MUST NOT override authenticated tenant context.
- **WF-4.3.6** Cross-tenant references MUST fail authorization without revealing protected existence.

## 4.4 Session Lifecycle

**Status: PREREQUISITE: v1.0**

The normative workflow is:

```text
CREATED -> CAPTURING -> SUBMITTED -> PROCESSING -> COMPLETED
```

Exceptional terminal lifecycle states are `EXPIRED` and `CANCELLED`. `INCONCLUSIVE` and `REVIEW_REQUIRED` are final decision outcomes attached to `COMPLETED`; they MUST NOT be lifecycle states. `INCONCLUSIVE` remains a valid Part III evidence status, but evidence and final decision contexts MUST be distinguished.

### Requirements

- **WF-4.4.1** The implementation MUST provide an unambiguous lifecycle representation.
- **WF-4.4.2** Lifecycle transitions MUST be explicitly defined.
- **WF-4.4.3** Illegal lifecycle transitions MUST be rejected.
- **WF-4.4.4** A session MUST NOT silently move between states without an authorized workflow action.

## 4.5 Lifecycle State Semantics

**Status: PREREQUISITE: v1.0**

- **`CREATED`**: the session exists but capture/submission has not begun.
- **`CAPTURING`**: the session is accepting or preparing evidence.
- **`SUBMITTED`**: client submission has been received and is ready for processing.
- **`PROCESSING`**: PaxLI is actively evaluating submitted evidence.
- **`COMPLETED`**: the workflow reached a terminal result that is durably recorded.
- **`EXPIRED`**: the permitted lifetime ended before successful completion.
- **`CANCELLED`**: an authorized cancellation terminated the session.

`INCONCLUSIVE` and `REVIEW_REQUIRED` are decision outcomes associated with a completed workflow and MUST NOT be represented as lifecycle states. `INCONCLUSIVE` as an evidence status remains distinct from final outcome `INCONCLUSIVE`.

### Requirements

- **WF-4.5.1** Each externally visible lifecycle state MUST have defined semantics.
- **WF-4.5.2** Clients MUST NOT infer state semantics from timestamps or missing fields.
- **WF-4.5.3** Internal execution states MUST NOT be exposed as public lifecycle states unless explicitly contracted.

## 4.6 Legal State Transitions

**Status: PREREQUISITE: v1.0**

The implementation MUST enforce legal transitions. Conceptually:

```text
CREATED -> CAPTURING -> SUBMITTED -> PROCESSING -> COMPLETED
CREATED/CAPTURING/SUBMITTED -> CANCELLED
CREATED/CAPTURING/SUBMITTED -> EXPIRED
PROCESSING -> COMPLETED with final INCONCLUSIVE when the expiration deadline is reached during processing
```

If the expiration deadline is reached while processing, the workflow MUST request a Decision Engine evaluation under the applicable policy. The Decision Engine MUST produce final `INCONCLUSIVE` with a stable expiration reason code before the session terminalizes as `COMPLETED`. Work completing after the deadline MUST NOT produce `VERIFIED` or `REJECTED`. If the Decision Engine cannot execute, its governed safe-failure path applies and the transition/result MUST retain the appropriate failure reason and required audit events.

A terminal session MUST NOT silently return to an earlier state.

### Requirements

- **WF-4.6.1** Illegal transitions MUST be rejected.
- **WF-4.6.2** Terminal states MUST be terminal unless an explicitly defined recovery mechanism exists.
- **WF-4.6.3** Transitions MUST be atomic with respect to concurrent requests.
- **WF-4.6.4** Every transition MUST produce the appropriate audit event.

## 4.7 Session Creation

**Status: PREREQUISITE: v1.0**

Authenticated tenant creation SHOULD establish `session_id`, `tenant_id`, policy reference, creation time, expiration, and initial state. The applicable policy MUST be identifiable before decisioning.

### Requirements

- **WF-4.7.1** Creation MUST establish tenant ownership.
- **WF-4.7.2** Creation MUST establish policy context or an unambiguous policy-selection mechanism.
- **WF-4.7.3** Creation MUST establish expiration semantics.
- **WF-4.7.4** Creation MUST be auditable.

## 4.8 Evidence Submission

**Status: PREREQUISITE: v1.0**

Evidence submission adds client or capture inputs to a session. Submission is distinct from processing. Receiving an image successfully does not establish validity, authenticity, face match, or verification.

### Requirements

- **WF-4.8.1** Successful submission MUST NOT imply successful verification.
- **WF-4.8.2** Submission MUST produce or associate evidence according to Part III.
- **WF-4.8.3** Submission validation failures MUST be distinct from processing failures.
- **WF-4.8.4** Submission MUST respect lifecycle constraints.
- **WF-4.8.5** Submission MUST be auditable where it affects the workflow.

## 4.9 Submission Idempotency

**Status: PREREQUISITE: v1.0**

Retryable submissions MUST support `Idempotency-Key`. The key is scoped to tenant, operation, and key value. Equivalent reuse resolves to the original operation/result; materially different reuse is rejected with `IDEMPOTENCY_KEY_REUSED`.

### Requirements

- **WF-4.9.1** Supported idempotent submissions MUST accept `Idempotency-Key`.
- **WF-4.9.2** Equivalent repeated submissions MUST NOT create duplicate logical operations.
- **WF-4.9.3** Materially different reuse MUST be rejected.
- **WF-4.9.4** Idempotency MUST be tenant-scoped.
- **WF-4.9.5** Idempotency retention/TTL MUST be explicitly defined.

## 4.10 Concurrent Submission Semantics

**Status: PREREQUISITE: v1.0**

Concurrent requests against a session MUST produce deterministic behavior. This includes simultaneous uploads, competing workers, cancellation versus processing, and expiration versus submission.

### Requirements

- **WF-4.10.1** Concurrent transitions MUST be serialized or safely coordinated.
- **WF-4.10.2** Concurrent submissions MUST NOT corrupt session state.
- **WF-4.10.3** Races between terminalization operations MUST produce one authoritative terminal result.
- **WF-4.10.4** Concurrency behavior MUST be contract-tested.

## 4.11 Processing Execution State

**Status: PREREQUISITE: v1.0**

Internal execution MAY use `NOT_STARTED`, `NOT_RUN`, `RUNNING`, `RETRYING`, `SUCCEEDED`, `TIMED_OUT`, and `FAILED`. These are runtime semantics and MUST NOT automatically become public outcomes. `NOT_RUN` MUST be mapped to an explicit Part III evidence state before evidence is accepted by the Decision Engine.

### Requirements

- **WF-4.11.1** Internal processing state MUST remain distinct from session lifecycle.
- **WF-4.11.2** Retry state MUST NOT be exposed as a final verification result.
- **WF-4.11.3** Processing failure MUST NOT automatically mean identity verification failure.

## 4.12 Processing State vs Session State

**Status: PREREQUISITE: v1.0**

A session may be `PROCESSING` while internal execution is `RETRYING` or `TIMED_OUT`. A timeout may eventually produce final outcome `INCONCLUSIVE`; these remain three different semantic layers.

### Requirements

- **WF-4.12.1** Session lifecycle and processing execution MUST have distinct representations where necessary.
- **WF-4.12.2** Internal failures MUST map to client outcomes through defined safety semantics.
- **WF-4.12.3** Infrastructure details MUST NOT leak into public semantics unless contracted.

## 4.13 Processing Initiation

**Status: PREREQUISITE: v1.0**

Processing begins when a session contains sufficient input for the applicable workflow. It MAY execute synchronously, but the API MUST remain capable of asynchronous execution.

### Requirements

- **WF-4.13.1** Processing initiation MUST be deterministic.
- **WF-4.13.2** Each attempt MUST be attributable to a session.
- **WF-4.13.3** Processing MUST use the applicable immutable policy version.
- **WF-4.13.4** Processing MUST NOT begin under an unauthorized tenant context.

## 4.14 Processing Completion

**Status: PREREQUISITE: v1.0**

Completion occurs when the Decision Engine produces a valid final outcome or a safe terminal non-verifying outcome. Outcomes are `VERIFIED`, `REJECTED`, `REVIEW_REQUIRED`, and `INCONCLUSIVE`.

### Requirements

- **WF-4.14.1** A completed decision MUST have an explicit outcome.
- **WF-4.14.2** The decision MUST reference its policy version.
- **WF-4.14.3** The decision MUST reference evidence used for decisioning.
- **WF-4.14.4** The decision MUST be durably persisted before external completion representation.

## 4.15 Retry and Recovery

**Status: PREREQUISITE: v1.0**

Retries recover transient failures and MUST NOT change evidence semantics or mutate existing evidence to obtain a desired result. Reprocessing creates a governed attempt or distinct derived evidence as required by Part III.

### Requirements

- **WF-4.15.1** Retryable and non-retryable failures MUST be distinguishable.
- **WF-4.15.2** Retries MUST be bounded.
- **WF-4.15.3** Retries MUST respect timeouts.
- **WF-4.15.4** Repeated processing MUST be idempotent for the logical operation.
- **WF-4.15.5** Retry exhaustion without a valid deterministic decision MUST produce final `INCONCLUSIVE` with a stable operational reason code.
- **WF-4.15.6** Retry behavior MUST be observable and auditable where required.

## 4.16 Timeout Semantics

**Status: PREREQUISITE: v1.0**

Every external or potentially blocking operation MUST have a bounded timeout. A timeout means the operation did not complete within its permitted window and MUST NOT automatically mean the verification condition failed.

### Requirements

- **WF-4.16.1** Blocking dependencies MUST have explicit timeout boundaries.
- **WF-4.16.2** Timeout MUST remain distinct from a verified negative result.
- **WF-4.16.3** Exhausted processing timeouts without a valid deterministic decision MUST map to final `INCONCLUSIVE` with a stable timeout reason code.
- **WF-4.16.4** Timeout behavior MUST be contract-tested.

## 4.17 Expiration

**Status: PREREQUISITE: v1.0**

A session expires when its lifetime is exceeded without successful completion. Expiration is a workflow event, not a verification decision, and MUST NOT imply `REJECTED`. The processing-expiration rule in Section 4.6 overrides this general rule when the deadline is reached during processing.

### Requirements

- **WF-4.17.1** Every session MUST have defined expiration semantics.
- **WF-4.17.2** Expiration MUST use server-controlled time.
- **WF-4.17.3** Expired sessions MUST reject operations no longer permitted.
- **WF-4.17.4** Expiration MUST be auditable.
- **WF-4.17.5** Expiration races MUST be deterministic.

## 4.18 Cancellation

**Status: PREREQUISITE: v1.0**

An authorized tenant MAY cancel a permitted session. Cancellation terminates the workflow but is not equivalent to `REJECTED`.

### Requirements

- **WF-4.18.1** Cancellation MUST require authorization.
- **WF-4.18.2** Cancellation MUST obey lifecycle rules.
- **WF-4.18.3** Cancellation MUST be auditable.
- **WF-4.18.4** Cancellation MUST NOT silently erase evidence.
- **WF-4.18.5** Cancellation MUST NOT change an already committed decision.

## 4.19 Terminal Session States

**Status: PREREQUISITE: v1.0**

Terminal lifecycle states are `COMPLETED`, `EXPIRED`, and `CANCELLED`. `INCONCLUSIVE` and `REVIEW_REQUIRED` are outcomes attached to `COMPLETED`; they remain terminal outcomes and MUST NOT become lifecycle states.

### Requirements

- **WF-4.19.1** Terminality MUST be explicit.
- **WF-4.19.2** Ordinary evidence submission MUST NOT be accepted after terminalization.
- **WF-4.19.3** Terminalization MUST be atomic.
- **WF-4.19.4** Terminal state MUST remain consistent with the persisted result.

## 4.20 Verification Decision

**Status: PREREQUISITE: v1.0**

The verification decision is the final semantic conclusion produced by the Decision Engine. The v1.0 outcomes are `VERIFIED`, `REJECTED`, `REVIEW_REQUIRED`, and `INCONCLUSIVE`. Only the Decision Engine may produce them, and they are never session lifecycle states.

### Requirements

- **WF-4.20.1** Final outcomes MUST originate from the Decision Engine.
- **WF-4.20.2** Final outcomes MUST be explicit.
- **WF-4.20.3** Final outcomes MUST identify the policy version.
- **WF-4.20.4** Final outcomes MUST identify the evidence context used.

## 4.21 Decision vs Session Lifecycle

**Status: PREREQUISITE: v1.0**

The dimensions are:

```text
Session lifecycle: CREATED, CAPTURING, SUBMITTED, PROCESSING, COMPLETED, EXPIRED, CANCELLED
Decision: VERIFIED, REJECTED, REVIEW_REQUIRED, INCONCLUSIVE
```

`lifecycle_state=COMPLETED` with any of the four decision outcomes is valid. An expired or cancelled session does not necessarily have a verification decision.

### Requirements

- **WF-4.21.1** Lifecycle and decision MUST remain distinct.
- **WF-4.21.2** A session MUST NOT be considered verified solely because it reached `COMPLETED`.
- **WF-4.21.3** Clients MUST inspect decision outcome to determine verification result.

## 4.22 `INCONCLUSIVE` Semantics

**Status: PREREQUISITE: v1.0**

Final `INCONCLUSIVE` is used when PaxLI cannot safely establish `VERIFIED` or `REJECTED`, including dependency outage, timeout, insufficient evidence, conflict, invalid input, or Decision Engine failure. It is not a disguised rejection.

### Requirements

- **WF-4.22.1** `INCONCLUSIVE` MUST be first-class.
- **WF-4.22.2** Processing failure MUST NOT be represented as `REJECTED` merely because it failed.
- **WF-4.22.3** The outcome MUST include a stable reason code.
- **WF-4.22.4** Underlying failure MUST remain observable and auditable without exposing sensitive internals to clients.

## 4.23 `REVIEW_REQUIRED` Semantics

**Status: PREREQUISITE: v1.0**

`REVIEW_REQUIRED` means automated verification identified a condition requiring authorized human or downstream adjudication. It is neither `VERIFIED` nor necessarily `REJECTED`.

### Requirements

- **WF-4.23.1** `REVIEW_REQUIRED` MUST be explicitly represented.
- **WF-4.23.2** Review requirements MUST have a defined reason.
- **WF-4.23.3** Only authorized actors may perform review actions.
- **WF-4.23.4** Review actions MUST be auditable.
- **WF-4.23.5** Reviewers MUST NOT silently modify underlying evidence.

## 4.24 Result Persistence

**Status: PREREQUISITE: v1.0**

A result MUST be durably persisted before external commitment. It SHOULD contain or reference session ID, decision, policy ID/version, configuration reference, evidence references, reason codes, creation time, and decision timestamp.

### Requirements

- **WF-4.24.1** A result MUST be durably persisted before external completion notification.
- **WF-4.24.2** The persisted result MUST be immutable as a historical decision record.
- **WF-4.24.3** The result MUST remain retrievable under authorization and retention rules.
- **WF-4.24.4** Persistence failure MUST prevent claims of durable completion.

## 4.25 Result Accessibility

**Status: PREREQUISITE: v1.0**

Once committed, an authorized tenant MUST retrieve the result through the verification-session API. Webhook state MUST NOT determine availability.

### Requirements

- **WF-4.25.1** A durable result MUST be retrievable through the authorized API.
- **WF-4.25.2** Webhook failure MUST NOT prevent retrieval.
- **WF-4.25.3** Retrieval MUST remain available after webhook exhaustion.
- **WF-4.25.4** Retrieval MUST respect tenant and credential authorization.

## 4.26 Webhook Interaction

**Status: PREREQUISITE: v1.0**

Webhooks are notifications, not authoritative result storage. Durable webhook-event persistence is internal. The required order is:

```text
Decision -> Durable Result -> Durable Webhook Event -> Required Audit -> Delivery Attempt
```

The durable webhook event is not externally observable; the required audit MUST be durable before delivery or any other external webhook effect.

### Requirements

- **WF-4.26.1** Webhook delivery MUST NOT precede durable result persistence.
- **WF-4.26.2** Delivery failure MUST NOT modify the result.
- **WF-4.26.3** Events MUST identify the underlying result.
- **WF-4.26.4** Delivery MUST be independently retryable.
- **WF-4.26.5** Receiving systems SHOULD support event idempotency.
- **WF-4.26.6** Webhook events MUST have durable identifiers and an explicit payload version.
- **WF-4.26.7** Webhook retry behavior MUST use bounded retry policies and durable delivery state.
- **WF-4.26.8** Webhook events, delivery state, and result references MUST remain tenant-scoped.
- **WF-4.26.9** Webhook configuration MUST use the authenticated tenant and authorization context. Background publication, retry, and delivery MUST use tenant ID from the durable event and the typed context `actor_type=SYSTEM`, `actor_id=paxli-webhook-delivery-service`, `authentication_method=INTERNAL_SCHEDULER`, `permission_used=WEBHOOK_DELIVER`, and `source=WEBHOOK_WORKER`.
- **WF-4.26.10** Required audit events for webhook publication and governed delivery actions MUST be durable before the corresponding observable effect.

## 4.27 Polling Interaction

**Status: PREREQUISITE: v1.0**

Polling through `GET /v1/verification-sessions/{id}` is an authoritative recovery mechanism subject to authentication, authorization, tenant isolation, and rate limits.

### Requirements

- **WF-4.27.1** The session API MUST expose enough state to determine processing completion.
- **WF-4.27.2** Completed results MUST be retrievable without webhook success.
- **WF-4.27.3** Polling MUST respect security and rate-limit boundaries.
- **WF-4.27.4** Clients MUST NOT depend exclusively on webhooks.

## 4.28 Crash Recovery

**Status: PREREQUISITE: v1.0**

Crashes MUST NOT corrupt semantics, create duplicate authoritative results, create contradictory decisions, silently mutate evidence, or lose tenant boundaries. Recovery MUST use durable state and idempotent operations.

### Requirements

- **WF-4.28.1** Recovery MUST be based on durable state.
- **WF-4.28.2** Worker restart MUST NOT create an unauthorized second final decision.
- **WF-4.28.3** Interrupted processing MUST resolve to a deterministic recoverable state.
- **WF-4.28.4** Crash recovery MUST be resilience-tested.

## 4.29 Duplicate and Replay Handling

**Status: PREREQUISITE: v1.0**

PaxLI MUST distinguish legitimate retries from replayed operations and support submission idempotency, webhook idempotency, and safe repeated retrieval.

### Requirements

- **WF-4.29.1** Equivalent submissions MUST NOT create contradictory state.
- **WF-4.29.2** Replay of a completed operation MUST obey terminal rules.
- **WF-4.29.3** Replay MUST NOT bypass authorization.
- **WF-4.29.4** Security-sensitive replay attempts SHOULD be observable.

## 4.30 Audit Requirements

**Status: PREREQUISITE: v1.0**

Workflow audit coverage MUST include session creation, evidence submission, processing start/completion, decision production, session completion, expiration, cancellation, review requirement, and result retrieval. Audit ordering MUST satisfy Part II Invariant 12: `Action -> Required Audit Event -> Observable Effect`.

### Requirements

- **WF-4.30.1** Verification-relevant lifecycle actions MUST produce durable audit events.
- **WF-4.30.2** Authorization-relevant workflow actions MUST be auditable.
- **WF-4.30.3** System actions MUST identify actor type `SYSTEM` through `AuthorizationContext`.
- **WF-4.30.4** Required audit failure MUST prevent the corresponding external effect where policy requires.
- **WF-4.30.5** Audit records MUST NOT contain raw credentials, tokens, biometric content, or unnecessary sensitive data.
- **WF-4.30.6** Webhook configuration, event publication, delivery, and retry actions MUST remain tenant-scoped and auditable.

## 4.31 Session Security

**Status: PREREQUISITE: v1.0**

Session access is governed by authentication, authorization, tenant isolation, credential capability, request context, and rate limiting. Session identifiers are not authorization credentials.

### Requirements

- **WF-4.31.1** Unauthenticated access MUST be rejected.
- **WF-4.31.2** Unauthorized tenant access MUST be rejected.
- **WF-4.31.3** Operational credentials MUST have only granted capabilities.
- **WF-4.31.4** Administrative operations MUST use the Management API and appropriate administrative credentials.
- **WF-4.31.5** Session IDs MUST NOT serve as authorization credentials.

## 4.32 Session API Contract

**Status: PREREQUISITE: v1.0**

The public API MUST expose workflow semantics without unnecessary internals. A client-visible representation SHOULD provide session ID, status, decision, timestamps, expiration, result, and reason codes where applicable. Worker IDs, circuit state, container IDs, retry internals, and stack traces MUST NOT be exposed unless deliberately contracted.

### Requirements

- **WF-4.32.1** Session API states MUST have stable documented semantics.
- **WF-4.32.2** Session API errors MUST follow the common API error contract.
- **WF-4.32.3** The API MUST distinguish processing state from final decision.
- **WF-4.32.4** The API MUST provide recovery through result retrieval.
- **WF-4.32.5** API evolution MUST follow Semantic Contract versioning and deprecation rules.

## 4.33 Conformance Requirements

**Status: PREREQUISITE: v1.0**

Workflow conformance MUST be tested at normative requirement level. Every normative workflow requirement MUST have a conformance test or formally justified verification mechanism.

### Requirements

- **WF-4.33.1** Every normative workflow requirement MUST have a conformance test or justified verification mechanism.
- **WF-4.33.2** Lifecycle tests MUST cover valid and invalid transitions.
- **WF-4.33.3** Concurrency tests MUST cover competing operations.
- **WF-4.33.4** Idempotency tests MUST cover equivalent and materially different requests.
- **WF-4.33.5** Failure tests MUST prove infrastructure failure does not become incorrect verification failure.
- **WF-4.33.6** Crash and recovery behavior MUST be tested.
- **WF-4.33.7** Webhook failure MUST be tested independently from result persistence.
- **WF-4.33.8** Result accessibility MUST be tested after webhook failure and exhaustion.
- **WF-4.33.9** Cross-tenant workflow access MUST be tested.
- **WF-4.33.10** Audit ordering MUST be tested for governed workflow actions.
- **WF-4.33.11** Processing-expiration races MUST be tested for deterministic safe behavior.
- **WF-4.33.12** Webhook identifiers, payload versions, bounded retries, tenant boundaries, and audit ordering MUST be tested.

## 4.34 Deferred Workflow Capabilities

### Durable Asynchronous Job Infrastructure

**Status: TARGET: v1.1**

The v1.0 API MUST remain async-capable, but a distributed durable queue is not itself a v1.0 semantic requirement. A future queue/worker architecture MUST preserve external workflow semantics.

### Advanced Human Review Workflow

**Status: TARGET: v1.1**

Reviewer assignment, queues, escalation, SLAs, multi-reviewer adjudication, and disagreement resolution are future capabilities. The v1.0 `REVIEW_REQUIRED` meaning remains valid without this complete subsystem.

### Session Resumption

**Status: TARGET: v1.1**

Future resumption across devices or interruptions MUST preserve session identity, tenant ownership, evidence lineage, authorization, auditability, and expiration.

## 4.35 Normative Workflow Model

```text
CREATED -> CAPTURING -> SUBMITTED -> PROCESSING
                                      |
                                      v
                                DECISION ENGINE
                                      |
                                      v
                                DURABLE RESULT
                                      |
                                      v
                                  COMPLETED

CREATED/CAPTURING/SUBMITTED -> EXPIRED
CREATED/CAPTURING/SUBMITTED -> CANCELLED

Decision outcomes: VERIFIED, REJECTED, REVIEW_REQUIRED, INCONCLUSIVE

Internal processing: NOT_STARTED, RUNNING, RETRYING, TIMED_OUT, FAILED, SUCCEEDED
```

Internal processing states MUST NOT redefine external verification semantics.

## 4.36 Workflow Safety Rules

1. A session is a workflow, not a verdict.
2. `COMPLETED` does not inherently mean `VERIFIED`.
3. Processing failure does not inherently mean `REJECTED`.
4. Expiration and cancellation are not rejection.
5. `INCONCLUSIVE` is a first-class outcome.
6. `REVIEW_REQUIRED` is distinct from success and rejection.
7. Processing state is separate from session lifecycle.
8. Evidence submission is separate from verification.
9. Results are durable before completion notification.
10. Webhooks are notifications, not authoritative result storage.
11. Polling remains a recovery mechanism.
12. Retries do not mutate historical evidence.
13. Concurrent operations resolve deterministically.
14. Crash recovery preserves decision integrity.
15. Tenant ownership is enforced throughout.
16. Governed workflow actions are auditable.
17. No workflow mechanism bypasses Decision Engine verdict authority.

## 4.37 Relationship to Earlier Semantic Parts

Part IV depends directly on Part II, especially Invariants 01, 02, 04, 05, 08, 09, 11, and 12, and on Part III's evidence states, provenance, integrity, immutability, requirements, conflicts, deletion, and Decision Engine boundary.

If a workflow rule conflicts with an architectural invariant or evidence semantic, the workflow rule MUST be revised rather than weakening the earlier contract.

## 4.38 Constitutional Principle

> **PaxLI must preserve the distinction between what happened, what the system observed, and what the system decided.**

The session records what happened in the workflow. Evidence records what PaxLI observed or established. The Decision Engine records what PaxLI decided under policy. These records may be related, but MUST NOT be treated as interchangeable.

A verification is successful only when the Decision Engine produces a valid `VERIFIED` decision and that decision is durably recorded.

## End of Part IV
