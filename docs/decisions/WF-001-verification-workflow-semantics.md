# WF-001 — Verification Workflow Semantic Reconciliation

**Status: FROZEN / APPROVED FOR IMPLEMENTATION**

This is the authoritative, durable record of the verification-session
workflow's semantic contract, reconciling Part IV
(`docs/specification/part-04-verification-workflow.md`) against the
codebase as it stood after DE-004 Phase 5. It is a normative implementation
dependency for `core/verification/` and its API/router layer, on equal
footing with `docs/decisions/DE-003-decision-semantics.md` for
`core/decision/`. Implementation transcribes this document; it does not
reinterpret it. If the existing codebase cannot represent something
written here, that is a conflict to report, not a license to invent a
different semantic.

**How this came to be frozen**: a reconciliation pass against Part IV
found that the *existing* session lifecycle model was itself
nonconformant — not merely missing a hook into the Decision Engine, but
conflating two dimensions Part IV requires kept separate (session
lifecycle state and final decision outcome). That finding, six follow-on
decisions, and this full design were reviewed and approved before any
implementation began. See the session history for the discovery
narrative; this document carries only the frozen result forward.

---

## 1. Lifecycle state machine (exact)

```python
class VerificationStatus(StrEnum):
    CREATED = "CREATED"
    CAPTURING = "CAPTURING"
    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
```

Seven values. `VERIFIED`, `REJECTED`, `REVIEW_REQUIRED`, `INCONCLUSIVE` are
**not** members — they are `DecisionOutcome` values
(`core/decision/enums.py`), a fully separate type, already built correctly
by DE-003. This freeze does not touch `DecisionOutcome`; it corrects
`VerificationStatus` to stop overlapping it.

```python
VALID_STATUS_TRANSITIONS: dict[VerificationStatus, frozenset[VerificationStatus]] = {
    CREATED:    frozenset({CAPTURING, SUBMITTED, EXPIRED, CANCELLED}),
    CAPTURING:  frozenset({SUBMITTED, EXPIRED, CANCELLED}),
    SUBMITTED:  frozenset({PROCESSING, EXPIRED, CANCELLED}),
    PROCESSING: frozenset({COMPLETED, CANCELLED}),   # deliberately NOT EXPIRED -- see §7
    COMPLETED:  frozenset(),
    EXPIRED:    frozenset(),
    CANCELLED:  frozenset(),
}

TERMINAL_STATUSES: frozenset[VerificationStatus] = frozenset(
    status for status, transitions in VALID_STATUS_TRANSITIONS.items() if not transitions
)
# = {COMPLETED, EXPIRED, CANCELLED} -- three values, not the six the
# pre-freeze enum produced. Still derived, never hand-duplicated
# (DE-004 Phase 4's own discipline, carried forward).
```

`CREATED → SUBMITTED` (skipping `CAPTURING`) is a legal direct edge:
§2 below establishes that evidence is not a hidden universal prerequisite
for `/submit`, so a session that goes straight from creation to submission
without ever entering `CAPTURING` must remain representable.

## 2. Submission trigger (frozen: explicit `/submit`, not auto-detected readiness)

`SUBMITTED` is reached only by an explicit client action —
`POST /v1/verification-sessions/{id}/submit` — never inferred from
evidence completeness. Rationale (frozen, not open for revisiting without
a new decision): `SUBMITTED` means *the client has finished providing
input and requests processing*; a policy's required-evidence set can
change across versions, but client intent must not be inferred from it.
This also gives the async-capable boundary named in §12 somewhere concrete
to sit: the same public contract survives a later move to background
execution because "submission" and "processing" are already two
observably distinct steps.

- First evidence submission on a `CREATED` session auto-advances it to
  `CAPTURING` (evidence is now being accepted). This is the *only*
  automatic transition in the whole model; every other edge requires an
  explicit action.
- `/submit` is legal from `CREATED` or `CAPTURING`. **Zero evidence at the
  time of `/submit` is not itself illegal** — whether the resulting
  evaluation can produce anything other than `INCONCLUSIVE`/
  `REQUIRED_EVIDENCE_MISSING` is entirely the policy's and the Decision
  Engine's concern (already correctly enforced there), not a workflow-level
  gate. The workflow must not silently invent an "at least one upload"
  universal rule Part IV never states.
- `Permission.VERIFICATION_SUBMIT = "verification:submit"` is a new,
  distinct operational permission (`core/security/authorization.py`),
  matching the existing granularity of `VERIFICATION_CREATE`/`_READ`/
  `_CANCEL` — submission is not folded into an existing permission.

## 3. Workflow → DecisionOrchestrator boundary

`VerificationWorkflowService`, in `core/verification/workflow.py` (frozen
location — no new `core/workflow/` package; this is the verification
session's own workflow, not a generic abstraction the codebase doesn't yet
need). Dependency direction is one-way and does not reverse:

```text
VerificationWorkflowService
          |
          v
   DecisionOrchestrator
          |
          v
     Decision Engine
```

The Decision Engine never manipulates session lifecycle state, and never
will under this contract — `core/decision/` gains no new dependency on
`core/verification/` beyond what it already has (the pinned policy read,
already built).

## 4. `PROCESSING` is a recovery state, not a second initiation path (frozen amendment)

There is exactly one public entry point: `submit()`. There is no public
"begin processing" call distinct from it. `PROCESSING` is only ever
*observed* by a caller that finds a session already there because an
earlier `submit()` call was interrupted (crash, timeout) before reaching
`COMPLETED` — never a state a caller deliberately targets as a starting
point.

`VerificationWorkflowService.submit()` is nonetheless safe to call (or
retry) from any status, and internally dispatches on the session's current
status rather than assuming it always starts at `CAPTURING`/`SUBMITTED`:

```text
submit(session_id, tenant_id):
    session = get(session_id, tenant_id)          # tenant-scoped, 404 if absent
    match session.status:
        CREATED, CAPTURING:
            transition_to(SUBMITTED)                # + SESSION_SUBMITTED audit
            persist
            fallthrough to SUBMITTED case
        SUBMITTED:
            transition_to(PROCESSING)                # + SESSION_PROCESSING_STARTED audit
            persist
            fallthrough to PROCESSING case
        PROCESSING:
            # recovery: an earlier call reached PROCESSING and did not
            # finish. evaluate_and_persist() is idempotent (DE-004 Phase
            # 3/5) -- this re-runs it rather than assuming the crash left
            # nothing behind.
            evaluation_reason = EXPIRATION if now >= session.expires_at else NORMAL
            decision = DecisionOrchestrator.evaluate_and_persist(
                session_id, tenant_id, evaluation_reason
            )
            transition_to(COMPLETED)                 # + SESSION_COMPLETED audit
            persist
            return session, decision
        COMPLETED:
            # idempotent replay: the same convergence-on-existing-result
            # pattern used throughout DE-004 -- fetch and return, no new
            # work, no new audit.
            decision = DecisionOrchestrator.get_for_session(session_id, tenant_id)
            return session, decision
        EXPIRED, CANCELLED:
            raise SessionAlreadyTerminalError
```

The conceptual distinction the amendment asks for lives in the *shape* of
this dispatch, not in two separate methods: the `CREATED`/`CAPTURING` and
`SUBMITTED` branches are *initiation*; the `PROCESSING` branch is
*recovery*, reachable only by finding a session already there, never by a
caller choosing to start there. A future durable-queue implementation
replaces the synchronous continuation inside the `SUBMITTED` branch with
enqueuing a job — the `PROCESSING` branch's recovery semantics are
unchanged, because a worker crashing mid-job is the same shape of problem
as a request handler crashing mid-request.

Lazily-triggered recovery (no new background sweep): the same `get()` path
that already lazily runs `expire_if_needed()` (§7) additionally detects a
session sitting in `PROCESSING` and invokes the recovery branch above
before returning — so a crashed `submit()` call self-heals on the next
`GET` even without an explicit client retry.

## 5. Decision → `COMPLETED` semantics

`COMPLETED` is reached from `PROCESSING` **unconditionally with respect to
decision outcome** — `VERIFIED`, `REJECTED`, `REVIEW_REQUIRED`, and
`INCONCLUSIVE` all terminate the lifecycle at `COMPLETED` identically. The
lifecycle transition table has no branch on `decision.outcome`; §10's read
projection is the only place outcome becomes visible.

## 6. Cancellation semantics

Legal from `{CREATED, CAPTURING, SUBMITTED, PROCESSING}` — every
non-terminal state. Illegal from `{COMPLETED, EXPIRED, CANCELLED}`.

`VerificationSessionService.cancel()` (Finding 5's fix): the existing
single hardcoded check (`if status == EXPIRED: raise SessionExpiredError`)
is replaced by attempting the transition and catching the *general*
illegal-transition condition as a named domain exception —
`SessionAlreadyTerminalError` — never a bare `ValueError` escaping to an
unhandled 500. The router maps it to 409, the same shape every other
already-terminal conflict in this codebase already uses.

**Concurrency**: cancellation racing a concurrent `submit()` reaching
`COMPLETED` first is resolved by §11's compare-and-swap, not by
application-level sequencing — whichever transition's conditional `UPDATE`
lands first wins; the loser's zero-row update becomes a clean
`ConcurrentTransitionError`, translated by the caller (cancel or submit,
whichever lost) into the appropriate 409.

## 7. Expiration semantics (two distinct destinations, not one)

Part IV's §4.6 draws a distinction that must not be collapsed:

```text
CREATED/CAPTURING/SUBMITTED, past expires_at
        -> EXPIRED                                      (no DecisionResult, ever)

PROCESSING, past expires_at
        -> COMPLETED, decision.outcome = INCONCLUSIVE,
           reason_codes = (SESSION_EXPIRED_DURING_PROCESSING,)
```

- `expire_if_needed()` (existing method, `VerificationSession`) widens its
  checked status set from `{CREATED, PROCESSING}` to
  `{CREATED, CAPTURING, SUBMITTED}` — same lazy-on-read mechanism, `PROCESSING`
  *removed* from this method's scope entirely.
- A `PROCESSING` session past its deadline is never transitioned to
  `EXPIRED` directly by any code path. It is only ever resolved by running
  `submit()`'s `PROCESSING` (recovery) branch, which itself checks
  `now >= expires_at` to select `EvaluationReason.EXPIRATION` over
  `NORMAL` before calling `evaluate_and_persist()` — reusing the exact
  mechanism DE-003 froze and DE-004 built, unconditionally producing
  `INCONCLUSIVE`/`SESSION_EXPIRED_DURING_PROCESSING` (the pure evaluator's
  own short-circuit, untouched by this document).

## 8. Evidence-submission legality (corrected from DE-004 Phase 4)

Legal only in `{CREATED, CAPTURING}` — **not** the `TERMINAL_STATUSES`
deny-list DE-004 Phase 4 built against the pre-freeze enum.
`EvidenceService.add()`'s guard becomes an allow-list
(`status not in {CREATED, CAPTURING}` → reject), not a deny-list of
terminals, because `SUBMITTED` and `PROCESSING` must also reject ordinary
evidence submission (the client already signaled "done") despite neither
being terminal. An allow-list fails safe automatically against any future
new status; a deny-list would need to remember to add one.

## 9. Session GET decision projection

`VerificationSessionResponse` gains an optional `decision` field, sourced
by a read-time lookup against `DecisionPersistenceService.get_for_session()`
(already exists, DE-004 Phase 3) — never a denormalized column on
`verification_sessions`. Populated if and only if `status == COMPLETED`;
`None` for every other status, never a partial or speculative decision.

```python
class PolicyReferenceResponse(BaseModel):
    id: str
    version: int
    hash: str

class DecisionProjection(BaseModel):
    outcome: DecisionOutcome
    reason_codes: tuple[str, ...]
    policy: PolicyReferenceResponse

class VerificationSessionResponse(BaseModel):
    ...  # existing lifecycle fields, unchanged
    decision: DecisionProjection | None = None
```

`DecisionResult`/`DecisionProvenance` remain the sole authoritative
decision record. The session row is never a second source of truth for
the outcome, even a cached one.

## 10. Idempotency fingerprint semantics (closes WF-4.9.3 / Finding 6)

Both session creation and evidence submission gain a stored fingerprint,
computed the same way `EvidenceResult.integrity_reference` and
`Policy.canonical_hash` already are (canonical JSON, SHA-256) — the same
pattern applied to two more write paths, not a new one:

```text
session creation fingerprint    = sha256(canonical_json({tenant_id, assurance_level, external_reference}))
evidence submission fingerprint = sha256(canonical_json({tenant_id, session_id, evidence_type, checksum}))
```

On `Idempotency-Key` replay: recompute the fingerprint from the *new*
request; compare to the *stored* fingerprint from the original write.
Match → return the original result unchanged (existing behavior). Mismatch
→ raise `IdempotencyKeyReusedError` → `409 IDEMPOTENCY_KEY_REUSED` (the
exact code WF-4.9.3 names). Additive migration: one nullable `fingerprint`
column on each idempotency-bearing table, same discipline as every prior
migration this project has done.

## 11. Lifecycle transition concurrency (new mechanism, small and precedented)

`VerificationSessionRepository.update()` today is a blind overwrite. This
freeze requires it become a conditional write:

```sql
UPDATE verification_sessions
SET status = :new_status, ...
WHERE id = :id AND tenant_id = :tenant_id AND status = :expected_current_status
```

Zero rows affected → `ConcurrentTransitionError`, translated by the
repository, never an application-level check-then-write race. Same
"the database is the final arbiter" discipline as every other race this
codebase resolves this way (partial unique indexes, the decision
persistence SAVEPOINT) — applied here for the first time to this specific
table, because this is the first mechanism that needed it.

## 12. Synchronous-vs-asynchronous execution boundary

`submit()` is a plain `async` method with no dependency on being called
from an HTTP handler specifically. `/submit` calls it synchronously and
returns the fully-resolved session (including the decision projection, if
reached) in one response for v1. Moving to a background-worker trigger
later changes *what calls* `submit()`'s continuation (a queue consumer
instead of a route handler) — the method's contract, the API response
shape, and the polling contract (§9) do not change. This is WF-4.13's
"MAY execute synchronously, but the API MUST remain capable of
asynchronous execution" made concrete: the boundary is the method
signature, not a queue that doesn't exist yet and isn't being built now.

## 13. Audit events (frozen: four specific new members, not one generic event)

```python
class AuditEventType(StrEnum):
    ...  # existing members unchanged
    SESSION_CAPTURING_STARTED = "SESSION_CAPTURING_STARTED"
    SESSION_SUBMITTED = "SESSION_SUBMITTED"
    SESSION_PROCESSING_STARTED = "SESSION_PROCESSING_STARTED"
    SESSION_COMPLETED = "SESSION_COMPLETED"
```

Chosen over a single generic `SESSION_LIFECYCLE_TRANSITIONED` event:
matches the existing vocabulary's granularity (every other lifecycle event
— `SESSION_CREATED`, `SESSION_CANCELLED`, `SESSION_EXPIRED` — is already
specific), and gives operations/security tooling a directly queryable
signal without needing to parse metadata to know what happened. Metadata
on each event MAY still carry `{from_status, to_status}` where useful, for
transition context beyond what the event name alone conveys.

Every one of these follows the existing, unmodified audit-before-effect
transaction shape (Invariant 12): the lifecycle transition does not commit
unless its audit event commits with it, same transaction, no new pattern.
`DECISION_PRODUCED`/`DECISION_ENGINE_FAILED` (DE-004 Phase 3/4) remain the
Decision Engine's own audit trail, unchanged and undiminished by these —
a `submit()` call that reaches `COMPLETED` produces *both*
`SESSION_PROCESSING_STARTED` beforehand, `DECISION_PRODUCED` (or
`_ENGINE_FAILED`) from the orchestrator, and `SESSION_COMPLETED`
afterward — each subsystem audits its own transitions; neither absorbs
the other's.

## 14. Dead code disposition

`core/verification/orchestrator.py` (`VerificationOrchestrator`) is
deleted, not built upon — same treatment as the dead `core/decision/engine.py`
scaffold removed in DE-004 Phase 1. It predates the semantic-contract
track, is used nowhere except one reliability unit test
(`tests/unit/test_reliability.py`), and independently encodes the exact
lifecycle/decision conflation this document corrects (it calls
`session.transition_to(VerificationStatus.INCONCLUSIVE)` directly). Its
one test is adapted to exercise the reliability retry/circuit-breaker
mechanism directly (`core/reliability/executor.py`'s
`execute_with_reliability`, or an equivalent minimal harness), not through
this now-deleted workflow class.

## 15. Deferred, confirmed unchanged

- **Webhooks** (Part IV §4.26): no infrastructure exists, none is built by
  this document. `REVIEW_REQUIRED` remains a decision outcome only —
  CLAUDE.md's own words, unchanged: *"`REVIEW_REQUIRED` does not imply
  that a human-review subsystem exists."*
- **Human review subsystem** (§4.23's adjudication actions, §4.34): deferred,
  `TARGET: v1.1` per Part IV itself.
- **`EngineReasonCode.DECISION_TIMEOUT`**: still DEFERRED exactly as
  recorded in `docs/decisions/DE-004-PHASE-5-CONFORMANCE.md` — nothing in
  this document changes that disposition or adds a runtime budget
  mechanism.
- **Durable asynchronous job infrastructure** (§4.34): §12 preserves the
  boundary; no queue, worker, or distributed-transaction framework is
  introduced now.

## 16. Traceability against Part IV (by section group)

| Sections | Disposition |
|---|---|
| 4.1-4.6 (identity, ownership, lifecycle, transitions) | §1 |
| 4.7 (creation) | Already conformant (DE-004 Phase 4 policy pinning); idempotency fingerprint added by §10 |
| 4.8-4.10 (submission, idempotency, concurrency) | §8, §10, §11 |
| 4.11-4.13 (processing states, initiation) | §3-4, §12; internal `core/reliability` states remain unconnected to lifecycle by construction, unchanged |
| 4.14 (processing completion) | Already conformant (DE-004); connected by §3-5 |
| 4.15-4.16 (retry, timeout) | Existing `core/reliability` mechanisms; no new finding, not session-lifecycle-specific |
| 4.17-4.19 (expiration, cancellation, terminality) | §6-7 |
| 4.20-4.23 (decision semantics, `INCONCLUSIVE`, `REVIEW_REQUIRED`) | Already conformant (DE-003/DE-004); §9 connects retrieval |
| 4.24-4.25 (result persistence, accessibility) | Already conformant (DE-004 Phase 3); §9 |
| 4.26 (webhooks) | Deferred, §15 |
| 4.27 (polling) | §9 |
| 4.28 (crash recovery) | §4, §11 |
| 4.29 (replay) | §10 |
| 4.30 (audit) | §13 |
| 4.31-4.32 (security, API contract) | Existing auth/authz layer, unchanged except the new `VERIFICATION_SUBMIT` permission (§2) and the response schema addition (§9) |
| 4.33 (conformance testing) | The implementation phase's obligation, not this document's — every requirement above needs a conformance test when built, matching every prior DE-00X phase's discipline |
| 4.34 (deferred capabilities) | §15, confirmed aligned |
| 4.35-4.38 (model summary, safety rules, relationship, constitutional principle) | Restated correctly by §1-9; nothing here contradicts them |

---

## Final decision table

| Item | Frozen decision |
|---|---|
| Lifecycle model | Seven-state lifecycle, fully separate from decision outcome |
| Submission trigger | Explicit `POST /submit`, never auto-detected from evidence completeness |
| Evidence-before-submit | Not required; zero evidence at `/submit` time is not itself illegal |
| Processing ownership | Workflow-owned (`VerificationWorkflowService`) |
| Decision ownership | `DecisionOrchestrator`-owned, dependency direction never reverses |
| Decision invocation | Synchronous for v1, inside one method whose contract survives a later async move |
| `PROCESSING` | A recovery state reachable only by re-entry, never a second public initiation path |
| Completion | Always `COMPLETED`, independent of decision outcome |
| Pre-processing expiry | `EXPIRED`, no `DecisionResult` ever produced |
| Processing-time expiry | `COMPLETED` + `INCONCLUSIVE`/`SESSION_EXPIRED_DURING_PROCESSING`, never `EXPIRED` |
| Cancellation | Legal from every non-terminal state; a named domain exception otherwise, never a bare `ValueError` |
| Lifecycle concurrency | Compare-and-swap conditional `UPDATE`, not application-level check-then-write |
| Evidence submission legality | Allow-list `{CREATED, CAPTURING}`, not a terminal-states deny-list |
| Session GET | Read-time `DecisionResult` projection; `None` unless `COMPLETED` |
| Decision storage | No denormalized decision authority on the session row, ever |
| Idempotency | Canonical request fingerprint comparison; mismatch → `IDEMPOTENCY_KEY_REUSED` |
| Lifecycle audit | Four specific new `AuditEventType` members, not one generic event |
| Workflow service | `VerificationWorkflowService` |
| Workflow location | `core/verification/workflow.py` (no new `core/workflow/` package) |
| Dead code | `core/verification/orchestrator.py` deleted; its one test adapted to test reliability mechanics directly |
| Webhooks | Deferred |
| Human review subsystem | Deferred |
| `DECISION_TIMEOUT` | Still deferred |

## Status

**WF-001 = FROZEN / APPROVED FOR IMPLEMENTATION.**

Implementation transcribes sections 1-15 above exactly. Any point where the
existing codebase cannot represent what is written here is a conflict to
report explicitly, per this project's standing rule, not a license to
silently choose a different semantic during coding.
