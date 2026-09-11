# DE-004 Phase 5 — Adversarial Conformance Record

**Status: CLOSED.** Hostile-review pass against the DE-003 §16 adversarial
property matrix and the DE-004 Phase 2-4 mandatory gates. Not an
implementation phase: this record either cites existing evidence for a
property, adds a new test where a genuine gap was found, or discloses a
property as not conformant/deferred where the implementation genuinely
does not satisfy it. Per the governing mandate for this phase: *"Do not
improve the architecture. Try to falsify it."* Nothing in `core/` changed
as a result of this pass except the new tests themselves — no property
below required a semantic fix, and none was weakened to make a test pass.

Vocabulary matches Part VIII: **CONFORMANT** (evidence demonstrates the
property holds), **NONCONFORMANT** (evidence demonstrates it does not),
**DEFERRED** (the mechanism the property depends on is not yet built, and
this is disclosed rather than silently assumed).

---

## Traceability matrix

| # | Property (DE-003 §16 / Phase 2-4 gates) | Verdict | Evidence |
|---|---|---|---|
| 1 | `decision.policy_reference == session.policy_reference` | CONFORMANT | Unit: [test_decision_evaluator.py:118](../../tests/unit/test_decision_evaluator.py#L118), [:135](../../tests/unit/test_decision_evaluator.py#L135) (pinned on every evaluator path, including both short-circuits). Real-Postgres, bit-for-bit, full pipeline: [test_decision_orchestration.py (integration):86](../../tests/integration/test_decision_orchestration.py#L86) |
| 2 | Decision survives deletion of evidence it references | CONFORMANT | Real-Postgres, using the actual Invariant-06 reconciliation delete path (not a simulated one): [test_decision_persistence.py (integration):188](../../tests/integration/test_decision_persistence.py#L188) |
| 3 | All six terminal session states reject evidence submission | CONFORMANT | Unit, parametrized over all six: [test_evidence_service.py:167](../../tests/unit/test_evidence_service.py#L167). Real Postgres+MinIO, same parametrization, plus proof rejection precedes any DB/storage mutation: [test_evidence_service_terminal_state.py:98](../../tests/integration/test_evidence_service_terminal_state.py#L98). Exhaustiveness of the terminal/non-terminal partition itself: [test_evidence_service.py:214](../../tests/unit/test_evidence_service.py#L214) |
| 4 | `evaluation_reason == EXPIRATION` → unconditional `INCONCLUSIVE` / `SESSION_EXPIRED_DURING_PROCESSING` | CONFORMANT | Unit, against a policy that would otherwise VERIFY *and* REJECT: [test_decision_evaluator.py:153](../../tests/unit/test_decision_evaluator.py#L153). Real Postgres, same adversarial shape, full pipeline: [test_decision_orchestration.py (integration):188](../../tests/integration/test_decision_orchestration.py#L188) |
| 5 | `default_outcome` can never be `VERIFIED` | CONFORMANT | Rejected at construction, not merely at evaluation: [test_decision_evaluator.py:520](../../tests/unit/test_decision_evaluator.py#L520) |
| 6 | Concurrent evaluation → exactly one decision, one `DECISION_PRODUCED` | CONFORMANT | Real Postgres, barrier-synchronized genuine transaction overlap (not scheduling luck — see the test's own docstring on why a plain `asyncio.gather` was rejected as insufficient proof), run 5× to rule out flakiness in the SAVEPOINT-based recovery path: [test_decision_persistence.py (integration):255](../../tests/integration/test_decision_persistence.py#L255) |
| 7 | Required-audit failure → zero durable decision rows, retry converges | CONFORMANT | Real Postgres: [test_decision_persistence.py (integration):152](../../tests/integration/test_decision_persistence.py#L152). Retry-converges half is structural (DecisionPersistenceService.persist() re-run from a clean session hits either a fresh insert or the UNIQUE-constraint recovery path — same mechanism proven by property 6, not a distinct code path needing its own retry test) |
| 8 | Threshold/model mismatch → `CALIBRATION_MODEL_MISMATCH` | CONFORMANT | Named-incompatible-version, absent-model-reference (the §17.2 addendum case), different-model-id, and priority-independence (the check is a pre-pass, not lazy): [test_decision_evaluator.py:573-618](../../tests/unit/test_decision_evaluator.py#L573) |
| 9 | Prohibited evidence: observable via `_present`, never an eligible input otherwise | CONFORMANT | [test_decision_evaluator.py:221](../../tests/unit/test_decision_evaluator.py#L221) (present alone doesn't reject), [:242](../../tests/unit/test_decision_evaluator.py#L242) (`_present` rule does) |
| 10 | Duplicate same-type effective evidence: DB invariant prevents it; defensive resolver stays deterministic | CONFORMANT | Real Postgres, direct two-row insert proving the partial unique index rejects the state: [test_evidence_result_persistence.py:268](../../tests/integration/test_evidence_result_persistence.py#L268). Defensive resolver (necessarily unit-level — the DB constraint makes the state unreachable through any repository call, so this can only be exercised by constructing the pathological input directly): [test_evidence_result_effective.py:35-83](../../tests/unit/test_evidence_result_effective.py#L35), including the deterministic tie-break and the mandatory observability signal |
| 11 | Conflict gate vs. no-matching-rule → distinct reason codes | CONFORMANT | [test_decision_evaluator.py:647](../../tests/unit/test_decision_evaluator.py#L647) |
| 12 | No active policy → session creation fails, no half-created session | CONFORMANT | Unit: [test_verification_session_policy_pinning.py:188](../../tests/unit/test_verification_session_policy_pinning.py#L188) (zero repository.add() calls). Real Postgres: [test_session_policy_pinning.py:96](../../tests/integration/test_session_policy_pinning.py#L96) (zero rows for the tenant) |
| 13 | Policy/engine reason-code collision → rejected before activation | CONFORMANT, and stronger than specified | [test_decision_evaluator.py:672](../../tests/unit/test_decision_evaluator.py#L672), parametrized over the full closed `EngineReasonCode` set. The rejection happens at `Rule`/`Gate` **construction** (a Pydantic validator), not merely at `PolicyService.create_and_activate()` — a colliding code cannot even be built into an object to pass to activation in the first place, which is strictly earlier and safer than "checked at activation" |
| 14 | Malformed evidence → rejected before persistence, never reaches the engine | CONFORMANT | Unit (rejection itself, at `EvidenceResultService.create()`): [test_evidence_result_service.py](../../tests/unit/test_evidence_result_service.py) `test_invalid_result_payload_persists_nothing_and_audits_nothing`. Full chain, real Postgres, through the orchestrator (rejected submission → absent from `list_effective_for_session()` → `REQUIRED_EVIDENCE_MISSING`, not a decision computed from corrupted data) — new this phase: [test_decision_orchestration_adversarial.py:306](../../tests/integration/test_decision_orchestration_adversarial.py#L306) |
| 15 | Superseded evidence → only the effective (superseding) row participates | CONFORMANT | Resolver-level, defensive fallback: property 10 above. **Orchestrator-level, the case this phase specifically went looking to break** — a stale `FaceMatch=FAIL` superseded by `FaceMatch=PASS`; asserts the orchestrator produces `VERIFIED`, not the `REJECTED` the stale row would have produced — new this phase, real Postgres: [test_decision_orchestration_adversarial.py:101](../../tests/integration/test_decision_orchestration_adversarial.py#L101) |
| 16 | Infrastructure/timeout/provider failure never silently becomes `REJECTED` | CONFORMANT for every failure path that exists; the timeout mechanism itself is **DEFERRED** — see below | See the dedicated discussion after this table |
| 17 | Decision persistence crash/failure → no externally durable unaudited decision | CONFORMANT | Same evidence as property 7 |
| — | **New: mutation-after-evaluation.** A real DB write (superseding the evaluated evidence) is injected in the actual gap between `evaluate()` returning a candidate and `persist()` committing it. The persisted decision must reflect what was evaluated, not what the database looks like by the time persistence runs | CONFORMANT | Constructed by hand-assembling the orchestrator's own steps to open a real, exploitable gap — not simulated. Real Postgres: [test_decision_orchestration_adversarial.py:186](../../tests/integration/test_decision_orchestration_adversarial.py#L186) |

---

## Property 16, in full: infrastructure failure and `DECISION_TIMEOUT`

Every failure path that actually exists in the implementation was checked
and found to route to `INCONCLUSIVE`, never `REJECTED`:

- Required evidence `UNAVAILABLE` (a provider outage) → `REQUIRED_EVIDENCE_MISSING`, proven for all three "no result produced" statuses: [test_decision_evaluator.py:308](../../tests/unit/test_decision_evaluator.py#L308).
- An unhandled evaluator exception (a bug, not a policy decision) → `DECISION_ENGINE_ERROR`, with its own required audit event: [test_decision_orchestration.py:424](../../tests/unit/test_decision_orchestration.py#L424).
- The pinned policy version cannot be re-fetched → `POLICY_VERSION_UNAVAILABLE`: [test_decision_orchestration.py:387](../../tests/unit/test_decision_orchestration.py#L387).
- The re-fetched policy's hash disagrees with the session's pin → `POLICY_INVALID`: [test_decision_orchestration.py:404](../../tests/unit/test_decision_orchestration.py#L404).

Every one of these is structurally incapable of producing `REJECTED`: that
outcome is reachable *only* through an explicitly matched `Gate`/`Rule` or a
policy-declared `default_outcome`, all of which are policy authorship, not
engine-detected failure. This is not a coincidence to be re-verified per
release; it is a fact about the evaluator's control flow proven separately
in [test_decision_engine_purity.py](../../tests/unit/test_decision_engine_purity.py).

**What is genuinely not conformant, disclosed rather than assumed**:
`EngineReasonCode.DECISION_TIMEOUT` is declared in the closed vocabulary
(DE-003 §8) and appears in DE-003's own traceability table against
DEC-5.26 ("runtime budget still unimplemented"), but grep confirms it is
referenced nowhere outside its own enum definition:

```
core/decision/enums.py:42:    DECISION_TIMEOUT = "ENGINE:DECISION_TIMEOUT"
```

No runtime budget, wall-clock ceiling, or timeout mechanism exists for
evaluation. In practice this is low-risk — the evaluator is pure, synchronous,
and bounded by `MAX_CONDITION_NODES`/`MAX_CONDITION_DEPTH`/`MAX_GATES`/`MAX_RULES`
(themselves DEC-5.26.1-4's complexity bound, already enforced at policy
activation), so an evaluation cannot run unboundedly long today. But the
*reason code* — the promise that a genuinely slow evaluation would be
caught and reported as `DECISION_TIMEOUT` rather than simply blocking the
caller indefinitely — has no enforcement behind it.

**Verdict: `DECISION_TIMEOUT` is DEFERRED, not CONFORMANT.** No test was
written to fabricate coverage for a mechanism that does not exist — that
would misrepresent conformance rather than establish it. This should be
tracked as a Deferred Architecture Register entry (DEF-9.x, no entry
number assigned here — none of this session's work has populated that
register, which is a pre-existing gap noted in this project's history) if
and when a real runtime budget becomes a requirement.

---

## What this phase deliberately did not do

- **No architectural change.** Every property above either already held
  (the large majority, built correctly in Phases 1-4) or was closed with a
  new *test*, never a new production code path. `core/`'s only changes in
  this phase are the three new adversarial test files themselves.
- **No fabricated coverage for `DECISION_TIMEOUT`.** Disclosed as DEFERRED
  above rather than given a test that would only prove the *reason code
  enum value exists*, not that any mechanism produces it.
- **No attempt to re-decide the session-lifecycle-sync question** raised
  and explicitly deferred in the Phase 4 orchestration commit. Still open,
  still out of scope here.
- **No new adversarial coverage for cross-tenant leakage into evaluation**
  beyond what already exists: `list_effective_for_session()` is
  tenant-scoped by the same SQL-WHERE-clause pattern proven exhaustively
  elsewhere in this codebase (`tests/contracts/security/test_tenant_isolation.py`),
  and the pure evaluator's own coherence check independently rejects
  cross-tenant evidence ([test_decision_evaluator.py:751](../../tests/unit/test_decision_evaluator.py#L751)). Re-deriving that proof a third time here would not have found anything new.

## Validation

Ruff clean. Mypy clean (157 source files — this phase added only test
files, no `core`/`infrastructure`/`apps` changes). Full suite run twice
consecutively against real PostgreSQL + MinIO after the three new
adversarial test files were added; results recorded in the corresponding
commit.

## Final status

**DE-004 — Phases 1 through 5 — CLOSED.**

The Decision Engine vertical slice (policy activation → session creation
→ policy pinning → evidence submission → effective-evidence resolution →
context assembly → pure evaluation → persistence → required audit) runs
end to end against real infrastructure and has survived a dedicated
attempt to falsify it against the frozen DE-003 semantics. This
establishes **implementation conformance within the scope actually
tested** — not "production ready," not "all of PaxLI complete," and
explicitly not covering session-lifecycle synchronization or a real
evaluation timeout mechanism, both disclosed above as open rather than
silently assumed closed.
