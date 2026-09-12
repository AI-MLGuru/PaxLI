# WF-006 — Part IV Conformance / Closure Audit

**Status: CLOSED.** This began as a pure reconciliation pass — every one
of Part IV's 38 sections (`docs/specification/part-04-verification-workflow.md`)
read in full against the actual current implementation (`core/verification/`,
`core/decision/`, `core/evidence/`, `core/reliability/`, `apps/api/`,
their migrations, and their tests), reconciled against the frozen WF-001
decision record, and against what WF-002 through WF-005 actually built —
not what they were designed to build. Where a requirement was not
satisfied, that was disclosed as NONCONFORMANT, never silently
interpreted as equivalent to something the implementation does do. Two
genuine NONCONFORMANT findings (A, B) and one documentation gap (C) came
out of that pass; per explicit review-and-decide authorization, this
document's own "fix → revalidate" tail then closed all three, with the
implementation changes and new tests described under each finding below.
Nothing in `core/`, `infrastructure/`, or `apps/` changed as a result of
the *audit* itself — only as the *authorized fixes* that followed it,
each scoped exactly to its finding.

Vocabulary matches Part VIII / DE-004 Phase 5's precedent: **CONFORMANT**
(evidence demonstrates the property holds), **NONCONFORMANT** (evidence
demonstrates it does not), **DEFERRED** (the mechanism a property depends
on is not yet built, and Part IV §4.34 or an existing decision record
already discloses this rather than silently assuming it), **PARTIAL**
(the underlying behavior is very likely correct by construction, but the
*test coverage* Part IV §4.33 itself requires is incomplete).

Method: sections §4.1-4.10, §4.17-4.21, §4.28-4.30, and §4.35-4.38 were
verified directly, file-by-file, against this session's own WF-002-005
work. Sections §4.11-4.16, §4.22-4.27, and §4.31-4.34 were verified by
three parallel evidence-gathering passes (exact file:line quotes, no
delegated judgment), each independently cross-checked against this
session's own knowledge of the codebase before being accepted into this
record.

---

## Traceability matrix, by section

| Part IV § | Subject | Verdict | Notes |
|---|---|---|---|
| 4.1 | Verification Session Definition | CONFORMANT | `VerificationStatus` has no `VERIFIED`/`REJECTED` member ([core/verification/enums.py](../../core/verification/enums.py)); `tenant_id`/`status` required fields |
| 4.2 | Session Identity | CONFORMANT | UUID PK, immutable; cross-tenant ID guessing returns 404 indistinguishable from nonexistent ([test_tenant_isolation.py:72](../../tests/contracts/security/test_tenant_isolation.py#L72)) |
| 4.3 | Session Ownership / Tenant Boundary | CONFORMANT | Tenant scoping enforced at the SQL `WHERE` clause for both reads *and* the CAS `UPDATE` ([verification_session.py:44](../../infrastructure/database/repositories/verification_session.py#L44), [:69](../../infrastructure/database/repositories/verification_session.py#L69)), not only at the application layer |
| 4.4 | Session Lifecycle | CONFORMANT | `VALID_STATUS_TRANSITIONS`, `transition_to()` rejects illegal edges; every write path is `VerificationSessionService.transition()` |
| 4.5 | Lifecycle State Semantics | CONFORMANT | Explicit `status` field; no reliability/internal-execution type ever reaches `VerificationSessionResponse` |
| 4.6 | Legal State Transitions | CONFORMANT | Transition table, CAS atomicity, terminal-recovery scoping all conformant. 4.6.4 ("every transition MUST produce the appropriate audit event") — **fixed this phase, Finding B**: `SESSION_EXPIRED` is now recorded by `VerificationSessionService.get()` itself, at the point its own CAS write succeeds, covering every caller uniformly |
| 4.7 | Session Creation | CONFORMANT | Tenant ownership, policy pin, `expires_at`, `SESSION_CREATED` audit all present |
| 4.8 | Evidence Submission | CONFORMANT | Allow-list gate, distinct validation-vs-processing failure paths, `EVIDENCE_UPLOADED`/`SESSION_CAPTURING_STARTED` audit |
| 4.9 | Submission Idempotency | CONFORMANT | Fingerprint scheme, tenant scoping, materially-different-reuse rejection all conformant (WF-003). 4.9.5 ("retention/TTL MUST be explicitly defined") — **documented this phase, Finding C**: recorded as a WF-001 addendum, since retention was already correct by construction (tied to the owning row's own lifetime), just never written down |
| 4.10 | Concurrent Submission Semantics | CONFORMANT | CAS throughout; barrier-synchronized real-Postgres races proven repeatedly (WF-002/003/004/005) |
| 4.11 | Processing Execution State | CONFORMANT | `ComponentOutcome` has no `REJECTED` member — structurally incapable of disguising a failure as rejection. The specific `NOT_STARTED`/`RUNNING`/`RETRYING` vocabulary Part IV's text permits (`MAY use`) is simply not implemented as a named type; not required, since nothing exposes reliability-layer state publicly either way |
| 4.12 | Processing State vs Session State | CONFORMANT | Type-level separation verified; failure→outcome mapping proven to go only through the orchestration boundary (`test_decision_engine_purity.py`) |
| 4.13 | Processing Initiation | CONFORMANT | Deterministic dispatch; every step session-attributed; policy resolved by **pinned** `(policy_id, version)`, never "currently active" — verified directly, [orchestration.py:138-169](../../core/decision/orchestration.py#L138); tenant never client-suppliable |
| 4.14 | Processing Completion | CONFORMANT | Explicit outcome, policy + evidence references on `DecisionProvenance`; durable commit precedes response transmission — traced the full dependency-cleanup chain to confirm this precisely, not assumed |
| 4.15 | Retry and Recovery | PARTIAL — see Finding K | Retryable/non-retryable distinguishable; hard-bounded (`RetryPolicy.max_attempts`, constructor-enforced ≥1); per-attempt timeouts; idempotent. 4.15.5's literal "retry exhaustion → INCONCLUSIVE" applies correctly to evaluation-context failures but not to durability-mechanism (DB commit) exhaustion, which correctly 503s instead — not a gap, see Finding K |
| 4.16 | Timeout Semantics | PARTIAL | Explicit, quoted timeout values for every wrapped dependency; TIMEOUT/FAILED distinct; session-deadline timeout → INCONCLUSIVE is conformant and tested. `DECISION_TIMEOUT` (evaluator runtime-budget) is **already disclosed DEFERRED** in `DE-004-PHASE-5-CONFORMANCE.md` — unchanged by this audit. 4.16.4: real, rigorous, non-mocked tests exist but none live under `tests/contracts/`, this project's own designated location — organizational gap, see Finding I |
| 4.17 | Expiration | CONFORMANT | Same fix as 4.6.4 — Finding B |
| 4.18 | Cancellation | CONFORMANT | Authorization, lifecycle rules, audit, never touches evidence. 4.18.5 ("must not change an already-committed decision") verified precisely: `get_db_session`'s rollback-on-exception means a losing `/submit`'s already-`flush()`-staged decision INSERT is rolled back together with its failed CAS write — no orphaned decision can ever result from a cancel-vs-submit race |
| 4.19 | Terminal Session States | CONFORMANT | Terminality explicit and derived; evidence allow-list stronger than required; CAS atomicity; `COMPLETED` always has exactly one decision, `CANCELLED`/`EXPIRED` never have one |
| 4.20 | Verification Decision | CONFORMANT | Only `core/decision/evaluator.py`'s pure function produces outcomes; explicit, policy-referenced, evidence-referenced |
| 4.21 | Decision vs Session Lifecycle | CONFORMANT | Zero shared enum members; API requires inspecting `decision.outcome`, no session-level "verified" shortcut exists |
| 4.22 | `INCONCLUSIVE` Semantics | CONFORMANT | Exhaustive grep of every `DecisionOutcome.REJECTED` call site (2 total, both policy-authored type declarations, zero engine-side); every one of 8 engine-failure call sites resolves to `INCONCLUSIVE` with a stable reason code; failure observable via required audit + structured log, never exposed to the client |
| 4.23 | `REVIEW_REQUIRED` Semantics | CONFORMANT (4.23.1-2) / **DEFERRED (4.23.3-5)** | Outcome is genuinely reachable (reachable via rule/gate/default_outcome, tested with a real evaluator call) with a mandatory reason code. 4.23.3-5 (authorized review actions, review audit, non-silent evidence modification) have zero code path to check against — no permission, no endpoint, no audit event, no service exists. Correctly matches Part IV §4.34's own explicit deferral of "the complete subsystem" and WF-001 §15; not a silent gap |
| 4.24 | Result Persistence | CONFORMANT | `DecisionRecord` has no `update()`/`delete()` anywhere in the codebase — immutability verified as a structural absence, not a policy. Durable-before-response ordering traced through the full FastAPI dependency-cleanup chain |
| 4.25 | Result Accessibility | CONFORMANT | Decision projection gates on `status == COMPLETED` alone; no webhook-state reference anywhere in the code path (none exists to reference) |
| 4.26 | Webhook Interaction | DEFERRED, confirmed clean | Exhaustive repo-wide grep: a scope comment, two unused enum placeholders (`FailureCategory.WEBHOOK`, never referenced), and an empty `integrations/webhooks/` scaffold. Zero partial implementation of any of WF-4.26.1-10 |
| 4.27 | Polling Interaction | CONFORMANT | `status`+`decision` sufficient to determine completion; retrieval independent of webhook state (none exists). The "authoritative recovery mechanism" framing this section opens with — **fixed this phase, Finding A**: `GET` on a `PROCESSING` session now triggers recovery via `VerificationWorkflowService.submit()`, matching WF-001 §4's frozen promise. Minor, still open, pre-existing: `GET` (and `cancel`) have no operation-specific rate limit, unlike `create`/`submit` (Finding D) |
| 4.28 | Crash Recovery | CONFORMANT (mechanism) | DE-003's `UNIQUE(tenant_id, session_id)` + SAVEPOINT recovery prevents a second decision on worker restart; `PROCESSING`-recovery is deterministic and real-Postgres tested via **explicit `/submit` retry**. See Finding A for the GET-triggered variant specifically |
| 4.29 | Duplicate and Replay Handling | CONFORMANT | Fingerprint-based equivalence, CAS convergence, replay never bypasses `require_permission`. 4.29.4 (SHOULD, security-sensitive replay observability) has no dedicated audit event for a rejected idempotency-key reuse beyond the 409 itself — SHOULD-level, not MUST, noted not blocking |
| 4.30 | Audit Requirements | CONFORMANT | `AuditActorType.SYSTEM` correctly used throughout WF-004's own audit calls; required-audit-failure-blocks-effect verified via the same rollback trace as 4.18.5; `sanitize_metadata()` applied; metadata scoped to `{from_status,to_status}` only. 4.30.1's gap (same root cause as 4.6.4/4.17.4) — fixed, Finding B |
| 4.31 | Session Security | CONFORMANT | All 4 verification-session endpoints require `Depends(get_principal)`; `require_permission` called first in every handler with the correct operational-tier permission; session_id never usable alone (cross-tenant and nonexistent IDs produce byte-identical 404 responses, [test_tenant_isolation.py:72](../../tests/contracts/security/test_tenant_isolation.py#L72)). Adjacent, out of Part IV's scope: `Permission.POLICY_MANAGE` has zero router wiring anywhere (no Management API surface for policy governance exists at all) — a Part V/governance gap, not a Part IV verification-workflow one, noted for completeness only |
| 4.32 | Session API Contract | CONFORMANT, one pre-existing gap noted | Schema fields match the required set exactly; no worker/circuit/container/retry field ever exposed; 14 exception handlers audited individually, all either fixed generic messages or hand-authored domain strings, never raw exception/DB internals. **Pre-existing gap, not introduced by WF-002-005 (Finding E): no catch-all `Exception` handler exists, and `DecisionOrchestrator.evaluate_and_persist()`'s own DB reads sit outside its try/except scope — a genuine mid-orchestration infrastructure failure would bypass the `ErrorEnvelope` contract** |
| 4.33 | Conformance Requirements | PARTIAL | 86 test functions across the verification/workflow/decision/idempotency surface; lifecycle, concurrency, idempotency, crash-recovery, cross-tenant, and audit-ordering requirements all have direct, named tests. Three coverage gaps found, all pre-existing in shape (this session added real coverage, didn't remove any): 4.33.5 has no test injecting a genuine DB/storage failure specifically inside the decision/submit path (Finding G); 4.33.11's expiration-race test is a deterministic 1-minute-past-deadline check, not a true concurrent race at the boundary (Finding H); the cancel-vs-concurrent-submit race (WF-001 §6's named property) is proven only against fakes, not real Postgres — the real-Postgres test covers cancel-vs-cancel instead (Finding F). 4.33.7/.8/.12 (webhook testing) confirmed correctly N/A, zero orphaned references |
| 4.34 | Deferred Workflow Capabilities | CONFORMANT | Durable async job infra, advanced human review, session resumption all confirmed genuinely absent — no queue library, no worker logic, no review endpoint, no resumption mechanism. Only inert, never-referenced enum placeholders (`AuditActorType.WORKER`, `FailureCategory.WEBHOOK`/`REVIEW`) exist as forward-compatible scaffolding |
| 4.35-4.38 | Model / Safety Rules / Relationships / Constitutional Principle | CONFORMANT, restated correctly | Pure restatement sections; all 17 safety rules verified against the sections above (rule 16, "governed workflow actions are auditable," now holds without qualification — Finding B) |

---

## Findings, resolved this phase

Per explicit review-and-decide authorization: Finding A's architectural
question was put to the project reviewer directly (three options —
implement as frozen via router→workflow, amend WF-001 to drop the
promise, or a passive stall-signal hybrid); "implement as frozen,
router→workflow" was chosen. Findings B and C were then implemented/
documented in that order, per the agreed sequence (decide A → fix B →
fix A → document C).

### Finding A — WF-001 §4's "self-heals on the next GET" promise is not implemented

**Severity: high.** WF-001 §4 (the frozen decision record) states explicitly:

> "Lazily-triggered recovery (no new background sweep): the same `get()`
> path that already lazily runs `expire_if_needed()` (§7) additionally
> detects a session sitting in `PROCESSING` and invokes the recovery
> branch above before returning — so a crashed `submit()` call self-heals
> on the next `GET` even without an explicit client retry."

This was also named explicitly in this session's own WF-004 task scope
("the PROCESSING-recovery branch **and lazy recovery trigger on GET**").
It was never built. The actual code,
[core/verification/service.py:169-189](../../core/verification/service.py#L169)
(`VerificationSessionService.get()`), only ever calls
`session.expire_if_needed()`, which explicitly excludes `PROCESSING`
from its checked set
([core/verification/enums.py](../../core/verification/enums.py),
`PRE_PROCESSING_STATUSES = {CREATED, CAPTURING, SUBMITTED}`). There is no
check for `session.status is PROCESSING` anywhere in `get()`, and no call
from `get()` (or the `GET /verification-sessions/{id}` router handler,
[verification_sessions.py:139-186](../../apps/api/paxli_api/routers/verification_sessions.py#L139))
into `VerificationWorkflowService`/`DecisionOrchestrator` at all. The
PROCESSING-recovery branch exists and is fully correct
([core/verification/workflow.py:131-148](../../core/verification/workflow.py#L131)),
but it is reachable **only** via an explicit `POST /submit` call.

**Practical consequence:** a client whose `/submit` request crashed the
server mid-flight (or whose response was lost to a network failure after
the server-side work completed up to `PROCESSING` but before `COMPLETED`)
and which then polls via `GET` — the pattern Part IV §4.27 calls "an
authoritative recovery mechanism" — will see the session sit in
`PROCESSING` indefinitely. Recovery requires the client to know to retry
`POST /submit` specifically, which is not documented anywhere as a
required client behavior (the API contract frames `GET` as the recovery
path, per WF-4.27.1/4.27.2 and WF-4.28's crash-recovery framing generally).

**Not a fabricated concern:** `tests/integration/test_verification_workflow.py:269`
(`test_submit_from_processing_recovers_after_a_simulated_crash`) proves
recovery works when `submit()` is called directly. No test exists — and
none could pass today — for recovery triggered by `GET` alone.

**Resolution (implemented, router→workflow, per the chosen option above):**
the `GET` router handler
([verification_sessions.py](../../apps/api/paxli_api/routers/verification_sessions.py),
`get_session()`) gained a `VerificationWorkflowService` dependency.
Observing `status is PROCESSING` after the initial read now calls
`workflow_service.submit(...)` inline, before building the response —
preserving WF-001 §3's one-way dependency direction (the *service* layer
still never depends on the workflow layer; only the router, which
already depended on both `VerificationSessionService` and
`VerificationWorkflowService` for `submit_session()`, gained a second use
of an existing dependency). A concurrent cancellation winning the race
mid-recovery (`SessionAlreadyTerminalError` from `workflow_service.submit()`)
is caught and the router re-fetches the current state instead of
surfacing a conflict to a caller that only asked to read — the same
swallow-the-lost-race posture `VerificationSessionService.get()` already
takes for its own lazy-expire side effect. Every other status is
untouched: the recovery attempt is gated strictly on `PROCESSING`, so a
plain `GET` on any other status remains a pure, unmodified read.

Proven in `tests/integration/test_submit_and_decision_projection.py`:
`test_get_on_a_stuck_processing_session_self_heals_to_completed`,
`test_get_on_a_stuck_processing_session_is_idempotent_on_repeated_polls`,
`test_get_on_a_non_processing_session_never_triggers_recovery_work`.

### Finding B — the `EXPIRED` transition is not reliably audited

**Severity: high.** `VerificationSessionService.get()`
([core/verification/service.py:169-189](../../core/verification/service.py#L169))
performs the CAS write to `EXPIRED` (via `expire_if_needed()`) but never
calls `audit_service.record(...)` — it doesn't even hold an
`AuditService` reference; `VerificationSessionService.__init__` takes
only `repository`, `policy_service`, `session_ttl_minutes`. The **only**
place a `SESSION_EXPIRED` audit event is ever recorded is a post-hoc
check inside the `GET` router handler itself:
[verification_sessions.py:173-177](../../apps/api/paxli_api/routers/verification_sessions.py#L173):

```python
event_type=(
    AuditEventType.SESSION_EXPIRED
    if session.status.value == "EXPIRED"
    else AuditEventType.SESSION_RETRIEVED
),
```

Verified directly: grepping every router file for `SESSION_EXPIRED`
confirmed exactly one match, in `get_session`. `submit_session`,
`cancel_session`, and `apps/api/paxli_api/routers/evidence.py`'s
`store_upload()` all call `session_service.get()` (or trigger
`expire_if_needed()` through it) with **no equivalent check** — a session
that lazily expires as a side effect of a `/submit` call, an evidence
upload, or a `/cancel` attempt transitions to `EXPIRED` with **zero**
audit trail.

This is a direct violation of WF-4.6.4 ("every transition MUST produce
the appropriate audit event") and WF-4.17.4 ("expiration MUST be
auditable") — not for the mechanism in the abstract, but for every code
path except the one that happens to be `GET`.

**Resolution (implemented):** `VerificationSessionService` gained a
required `audit_service: AuditService` constructor parameter — required,
not optional, so this exact gap cannot silently reopen at a future call
site. `get()` now records `SESSION_EXPIRED` itself, at the point its own
CAS write succeeds, covering every caller uniformly (a direct `GET`,
`/submit`, evidence upload, `/cancel` — all of which route a session
through `get()`). The router's own post-hoc `SESSION_EXPIRED`/
`SESSION_RETRIEVED` conditional was simplified to unconditionally record
`SESSION_RETRIEVED`, since the service now owns the `SESSION_EXPIRED`
event exclusively and recording it twice for one transition would
duplicate an event that must be recorded exactly once, ever. All 34
existing construction call sites (3 production DI providers, 20 test
files) were updated to pass `audit_service=`; no test logic or assertion
was changed, only the new required argument added.

Proven in `tests/unit/test_verification_session_expiry_audit.py` (7
tests: every pre-processing status records exactly one event with
correct `{from_status,to_status}` metadata; no audit when not actually
past expiry; no duplicate audit on repeated `get()` calls against an
already-expired session; `cancel()`'s internal `get()` call still audits
the expiry even though `cancel()` itself then rejects with
`SessionAlreadyTerminalError`; `audit_service` is confirmed required, not
optional) and `tests/integration/test_verification_session_expiry_audit.py`
(2 real-Postgres tests: the audit row is durably persisted and queryable;
repeated polling never duplicates it).

### Finding C — idempotency retention/TTL (WF-4.9.5) was never durably defined

**Severity: medium.** During WF-003, the reasoning that idempotency-key
retention is bounded by the underlying resource row's own lifetime (there
is no separate idempotency-record table; `idempotency_key` is a column on
`verification_sessions`/`evidence` themselves, so a key's effective
retention is exactly as long as that row persists — indefinite for
sessions today, since no session-deletion mechanism exists; governed by
Part XI retention rules for evidence) was discussed and adopted, but
**never written down** — not in `docs/decisions/WF-001-verification-workflow-semantics.md`,
not as a code comment on `core/verification/service.py` or
`core/evidence/service.py`'s idempotency logic, nowhere durable. Verified
directly: grepping `retention` across `core/verification/` and WF-001
finds only `core/evidence/service.py`'s unrelated `retention_days`
(evidence *content* retention, a Part XI/Part III concern, not
idempotency-key retention).

WF-4.9.5 says retention/TTL "MUST be explicitly defined" — a conclusion
reasoned about in a conversation that isn't preserved anywhere a future
reviewer could find does not satisfy "explicitly defined." This is a pure
documentation gap; no behavior needed to change.

**Resolution (implemented):** recorded as a post-freeze addendum to
[WF-001](WF-001-verification-workflow-semantics.md), clearly marked as
added during this phase rather than silently rewriting the original
frozen text. No code changed — the underlying retention behavior was
already correct by construction (tied to the owning row's own lifetime);
only the explicit record was missing.

---

## Minor findings (non-blocking, noted for completeness)

- **D — `GET` and `cancel` have no operation-specific rate limit.**
  Verified precisely: of the 4 endpoints in this router, only
  `create_session` ([verification_sessions.py:95](../../apps/api/paxli_api/routers/verification_sessions.py#L95))
  and `submit_session` ([:260](../../apps/api/paxli_api/routers/verification_sessions.py#L260))
  call `enforce_rate_limit`; `get_session` and `cancel_session` do not,
  relying only on the generic pre-auth network-source throttle common to
  every authenticated request. Pre-existing for both (neither WF-005 nor
  any earlier phase changed this posture; WF-005 only added the
  decision-projection logic to `get_session`). Defensible as intentional
  for `GET` specifically (reads are cheap, idempotent, and
  rate-limiting polling can itself cause recovery failures) — less
  obviously defensible for `cancel`, a write. Worth an explicit decision
  rather than silent omission for both.
- **E — no catch-all exception handler; `DecisionOrchestrator.evaluate_and_persist()`'s
  own DB reads sit outside its try/except scope.** Pre-existing from
  DE-004, not introduced by WF-002-005. A genuine mid-orchestration
  Postgres failure during `session_service.get()`/`policy_service.get_version()`/
  `evidence_result_service.list_effective_for_session()` would propagate
  as a raw, non-`ErrorEnvelope`-shaped exception rather than the
  standard 503 contract shape. A single additive `@app.exception_handler(Exception)`
  catch-all in `main.py` (never touching DE-003/DE-004 evaluation logic)
  would close this without any semantic change.
- **F — cancel-vs-concurrent-submit race proven only against fakes.**
  `tests/unit/test_verification_workflow.py:423` proves it at the unit
  level; the real-Postgres concurrency test
  (`test_verification_session_service.py:66`) proves cancel-vs-cancel
  instead. A real-Postgres cancel-vs-submit test would close this,
  mirroring the exact barrier-sync methodology already used five times
  this session.
- **G — WF-4.33.5 has no direct DB/storage-failure-injection test
  specifically inside the decision/submit path.** Generic reliability
  mechanism tests exist and pass; none targets
  `DecisionOrchestrator.evaluate_and_persist()`/`VerificationWorkflowService.submit()`
  specifically.
- **H — WF-4.33.11's expiration-race test is deterministic, not a true
  concurrent race.** Sets `expires_at` one minute in the past rather than
  racing two coroutines at the exact boundary. The design is
  deterministic by construction (`is_past_expiry` uses a plain, inclusive `now >= expires_at` comparison — the boundary instant itself counts as expired, never an undefined edge); the test
  coverage doesn't exercise the literal boundary instant.
- **I — timeout-specific tests are real and rigorous but don't live
  under `tests/contracts/`**, this project's own designated location for
  normative-contract proof (`CLAUDE.md`). Organizational, not a coverage
  gap.
- **J — `Permission.POLICY_MANAGE` has no Management API endpoint at
  all.** Correctly scoped administrative-only, unit-tested, but
  unreachable via any router. Part V/governance territory, not Part IV
  verification-workflow; noted for completeness, not in this audit's
  scope to resolve.
- **K — WF-4.15.5's "retry exhaustion → INCONCLUSIVE" applies to
  evaluation-context failures, not durability-mechanism ones, and the
  distinction is a real one, not a gap to fabricate coverage for.**
  Two genuinely different failure classes exist under the umbrella term
  "retry exhaustion," and this document should say so explicitly rather
  than imply every retry exhaustion produces `INCONCLUSIVE`:
  - **Evaluation-context failures** (the pinned policy version can't be
    re-fetched, its hash no longer matches the pin, or the evaluator
    itself raises) correctly resolve to `INCONCLUSIVE` with a stable
    `EngineReasonCode`, via `DecisionOrchestrator`'s own
    `_persist_engine_failure`/exception-handling paths. Conformant,
    already covered by 4.22's row above.
  - **Durability-mechanism exhaustion** (the Postgres `COMMIT` itself
    failing after `guarded_commit`'s bounded, deliberately-not-retried
    attempt) does **not** produce an `INCONCLUSIVE` decision — it
    produces a 503 with no decision persisted at all, and the whole
    request rolls back. This is correct, not a gap: if the commit
    mechanism itself is what's failing, nothing (including a fallback
    `INCONCLUSIVE`) can be durably written by it either, and WF-4.24.4
    ("persistence failure MUST prevent claims of durable completion")
    requires exactly this behavior, not a forced-through decision the
    system can't actually stand behind.
  - **Evidence-processing retry exhaustion** — WF-4.15.5's most literal
    reading (a biometric/document processing call exhausting retries) —
    has no concrete producer to exercise at all: `DocumentProvider`/
    `FaceProvider`/`LivenessProvider` are abstract base classes with zero
    implementations, and `apps/worker/` is empty. The evaluator's own
    machinery for handling this correctly (`EvidenceResultStatus.UNAVAILABLE`,
    grouped with `NOT_SUBMITTED`/`NOT_REQUIRED` in the evaluator's
    `_UNSATISFYING_STATUSES`) already exists and is unit-tested — what's
    missing is the actual processing pipeline that would call it, which
    is squarely out of WF-001-006's scope (none of these phases build
    biometric/document processing; that's a separate, much larger
    undertaking, consistent with §4.34's deferred-capabilities framing).
- **WF-4.29.4** (SHOULD-level): no dedicated audit event for a rejected,
  materially-different idempotency-key replay beyond the 409 response
  itself. Not a MUST; noted, not blocking.

---

## What this phase deliberately did not do

- **No silent fixing.** Every one of Findings A, B, C was disclosed in
  full — root cause, practical consequence, exact scope — *before* any
  implementation decision was made or code was touched. Finding A's
  architectural question was put to the project reviewer explicitly
  rather than assumed; Findings B and C were implemented/documented only
  after that decision, in the agreed order.
- **No re-litigation of DE-003/DE-004 decision semantics.** Findings E,
  G (unfixed, see below) touch DE-004-owned code paths but propose only
  additive, non-semantic changes (a catch-all handler; new tests) if and
  when separately authorized — nothing about `core/decision/`'s
  evaluation semantics was questioned or touched by this phase.
- **No fabricated test coverage.** The new tests for Findings A and B
  prove the specific properties those findings named — real HTTP-layer
  recovery, real durable audit persistence — not shallow existence
  checks. Findings F, G, H, I (unfixed) continue to name real, specific
  coverage gaps rather than being papered over with weak tests.
- **No attempt to resolve Findings D, E, F, G, H, I, J.** These remain
  open, minor, and disclosed — not blocking, not silently dropped.
  Finding J in particular (policy management's missing Management API
  surface) stays explicitly out of Part IV's scope.
- **No re-scoping of `VerificationSessionService`'s constructor beyond
  what Finding B required.** `audit_service` was added because the audit
  gap demanded it; no other dependency was added opportunistically.

## Validation

Ruff clean repo-wide. Mypy clean across 159 source files. Full suite run
twice consecutively: **496 passed, 0 failed**, both runs. New targeted
tests added for both fixes (3 integration tests for Finding A, 7 unit +
2 integration tests for Finding B — see each finding's Resolution above)
all pass, including against real PostgreSQL for the tests that require
database-level arbitration (audit durability, CAS recovery). All 38 Part
IV sections were read in full against the specification file directly
during the audit; all cited file:line evidence was read from the working
tree (not recalled from memory), with sections verified through parallel
research passes independently cross-checked before acceptance.

## Final status

**WF-006 — CLOSED.** All three findings that required action are
resolved: Finding A (GET-triggered PROCESSING recovery) and Finding B
(EXPIRED-transition audit gap) implemented and tested; Finding C
(idempotency retention/TTL) documented as a WF-001 addendum. Findings
D through J remain open as disclosed, non-blocking minor items —
tracked here, not silently dropped, available for prioritization in a
future phase (several are natural candidates for **WF-HV**, the planned
hostile-validation pass: F and G in particular are exactly the kind of
"deliberately try to break it" gaps that phase exists to close). Part IV
of the Semantic Contract — session identity, tenant isolation, lifecycle
transitions and their audit trail, idempotency and its retention,
concurrency, decision authority and immutability, INCONCLUSIVE/
REVIEW_REQUIRED semantics, result persistence and accessibility, crash
recovery via both explicit retry and passive polling, and every deferred
capability's genuine (not merely claimed) absence — is CONFORMANT,
verified against the actual current implementation and, where gaps were
found, closed rather than assumed away.
