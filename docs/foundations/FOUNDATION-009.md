# Foundation-009 — Policy Governance Infrastructure

**Status:** CLOSED
**Closed:** 2026-09-10
**Depends on:** Foundation-002 (`AssuranceLevel`, reused not redefined), Foundation-004 (audit), Foundation-006 (tenant isolation pattern, `Permission`/`require_permission`), Foundation-007 (reliability wiring, reused automatically via the shared unit of work), Foundation-008 (`EvidenceResultType` + `SCHEMA_REGISTRY` — hard dependency for semantic condition validation)
**Normative basis:** Part V §5.8–5.12 (Policy Definition/Schema/Validation/Normalization/Versioning) and §5.13–5.17 (declarative condition model), cross-referenced against Part II Invariant 07 (Policy Immutability, §7.1–7.10) and Invariant 08 §8.7 (tenant scoping), Part VII §7.23–7.24 (Policy Security and Governance)

## Identity

Part V's normative policy object — the authoritative, immutable configuration a future Decision Engine will read — had no data model or persistence anywhere in the codebase before this foundation. Foundation-009 closes that gap: `core/policy/` and its persistence layer establish **"this is the authoritative, immutable policy that exists."** It deliberately does not establish "given this evidence, this is the decision" — that remains the future Decision Engine's exclusive responsibility.

> **Foundation-009 establishes the authoritative, immutable policy store; it does not evaluate policies or produce verification decisions.**

## Scope boundary (as approved, verified against the implementation)

**In scope, delivered:** `VerificationPolicy` identity and tenant ownership; policy schema/version; canonical normalization; validation (schema, semantic, complexity); immutable versions; policy creation; activation; historical version preservation; rollback by activating a content-identical new version; policy status/lifecycle (`ACTIVE`/`SUPERSEDED`); policy integrity/hash; authorization boundary (`Permission.POLICY_MANAGE`); audit-before-effect; persistence and repository; policy retrieval by tenant/version; conformance and security testing.

**Explicitly out of scope, untouched:** condition *evaluation*, gates, rules, thresholds, weighted scoring, conflict resolution, decision aggregation, `VERIFIED`/`REJECTED`/`REVIEW_REQUIRED`/`INCONCLUSIVE` determination, the Decision Engine, policy execution, arbitrary executable policy code. No router, no `apps/` dependency-injection wiring — nothing invokes `PolicyService` yet, matching Foundation-008's precedent of shipping domain + persistence ahead of API wiring. Scope-lock verified: nothing in `core/policy/` imports or references `core/decision/`, evaluates a `Condition` tree, or produces a verification-status value.

## Key architectural decisions (approved, with two deviations surfaced and accepted)

1. **Two-state lifecycle (`ACTIVE`/`SUPERSEDED`) only.** Part V §5.36 defers staged/shadow/simulation policy states for v1.0; nothing normative requires an intermediate state between submission and activation.
2. **Rollback always creates a brand-new version** with content identical to the target historical version, then activates that new version normally. No row is ever reactivated in place — a stronger guarantee than Invariant 07 strictly requires, chosen to eliminate any ambiguity about whether a status flip counts as mutation.
3. **Applicability key for v1 is `(tenant_id, assurance_level)`**, enforced by a PostgreSQL partial unique index — deliberately *not* encoded as a permanent assumption that assurance level is the only future applicability dimension. A future foundation can widen the index without a table redesign.
4. **Full structural rigor for the condition model (`EvidenceCondition`/`AllOf`/`AnyOf`/`Not`)**, because Foundation-008 makes that rigor possible today (real `evidence_type`/field references). `gates`/`rules`/`thresholds`/`conflict_resolution` are validated-but-loosely-typed, schema-versioned envelopes for v1 — bounded, guaranteed non-executable, but not fully modeled, deferred to when the actual Decision Engine reveals what they need.
5. **`EvidenceSchemaCatalog` boundary.** Semantic condition validation asks a narrow domain-facing Protocol (`is_known_evidence_type`, `supports_field`) rather than importing Foundation-008's `SCHEMA_REGISTRY`/Pydantic classes directly. The concrete adapter (`core/evidence_result/schema_catalog.py::EvidenceResultSchemaCatalog`) lives in the evidence_result package and satisfies the Protocol structurally — neither package imports the other's contract type in the reverse direction. Module placement was an implementation call; the decoupling property itself was the approved requirement.
6. **Single `POLICY_ACTIVATED` audit event** covering both fresh activation and rollback, distinguished by `activation_type` (`INITIAL`/`ROLLBACK`) plus `previous_active_policy_id`/`previous_active_version`/`rollback_source_policy_id` in metadata — never the full policy body.
7. **`policy_id` is caller-supplied** (a human-meaningful slug), gated by a new administrative-only `Permission.POLICY_MANAGE`, mirroring `CREDENTIAL_MANAGE`.

**Two deviations from the discovery report's literal wording, surfaced during implementation and accepted:**

- **Statement ordering is supersede-then-insert, not insert-then-supersede.** PostgreSQL partial unique indexes are checked per-statement and cannot be made deferrable, so inserting a second `ACTIVE` row while the old one is still `ACTIVE` would violate the constraint immediately, mid-transaction. Both operations remain inside the same unit of work (`get_db_session()`), so an insertion failure still rolls the supersession back — the net atomicity/audit-before-effect guarantee is unchanged.
- **The concurrency-test methodology required correction, not the production code.** A first attempt at proving question 8 (concurrent activation) via a plain `asyncio.gather()` of two full `create_and_activate()` calls passed misleadingly — against a fast local Postgres, one coroutine ran flush-through-commit to completion before the other's first `await` was ever scheduled, so the two transactions never overlapped and both "won" (correctly, since the second legitimately superseded the first's already-committed row — not a bug). The test was rewritten with an `asyncio.Event` barrier that forces the second transaction's `INSERT` to genuinely start while the first's is still open and uncommitted, so PostgreSQL's real index-level locking — not scheduling luck — is what the test proves. That first barrier design itself had a deadlock hazard: if the first transaction failed for an unrelated reason (stale test data from an earlier debugging run), it returned before ever signaling the event, leaving the second task waiting forever. Fixed by moving the signal into a `finally` block so the barrier always releases. Both corrections are documented inline in `tests/integration/test_policy_persistence.py`. These were test-design mistakes caught and fixed during the same session, never committed as production defects.

## Requirement conformance

| Requirement | Status | Evidence |
|---|---|---|
| Invariant 07 §7.1–7.6 (immutable version identifier, no in-place modification, new version per change, auditable identity/version) | CONFORMANT | No `update()` beyond the narrow `mark_superseded` status/timestamp transition; `test_create_and_activate_persists_and_audits` (unit + real-Postgres) |
| Invariant 07 §7.7/7.8 (validated before activation; invalid policies MUST NOT become active) | CONFORMANT | `validate_policy_content` runs before any persistence; `test_invalid_policy_persists_nothing_and_audits_nothing` |
| Invariant 07 §7.9 (rollback activates a previous valid version, never mutates history) | CONFORMANT | `test_rollback_creates_a_new_version_content_identical_to_the_target` (unit) + `test_rollback_creates_a_new_version_original_untouched` (real Postgres): target row's `id`/`version`/`status` unchanged, new row gets a new `id`/`version`, `canonical_hash` proves content equivalence |
| Invariant 07 §7.10 (historical records retain original policy version) | CONFORMANT | `list_versions`; superseded rows are never deleted or altered beyond `status`/`superseded_at` |
| Invariant 08 §8.7 (policy tenant scoping) | CONFORMANT | `test_cross_tenant_get_returns_none` (real Postgres) |
| `DEC-5.8.1–5.8.4` (policy definition, no arbitrary executable code) | CONFORMANT | `_FORBIDDEN_ENVELOPE_KEYS` guard in `validation.py` rejects `code`/`eval`/`exec`/`script`/`__import__`-keyed envelope content; `test_gate_envelope_rejects_executable_shaped_keys` |
| `DEC-5.9`/`5.10` (schema, semantic, complexity validation) | CONFORMANT | `test_condition_referencing_unknown_evidence_type_is_rejected`, `test_condition_referencing_unknown_field_on_a_real_type_is_rejected` (real cross-foundation check against Foundation-008's actual schemas), `test_complexity_bound_rejects_an_oversized_tree` |
| `DEC-5.11` (canonical normalization + integrity hash) | CONFORMANT | `test_reordered_all_of_children_hash_identically` (commutative combinator stability), `test_genuinely_different_conditions_hash_differently`, `test_hash_is_deterministic_across_repeated_calls` |
| `DEC-5.12.1–5.12.4` (versioning, immutability, rollback semantics) | CONFORMANT | See Invariant 07 rows above |
| `DEC-5.13–5.17` (declarative condition model) | CONFORMANT for the schema; N/A for evaluation | Discriminated-union Pydantic model with full round-trip/complexity tests; nothing evaluates a condition against evidence |
| `DEC-5.18–5.23` (gate/rule/threshold/conflict-resolution *evaluation*) | N/A — explicitly the Decision Engine's scope, not this foundation's | — |
| `DEC-5.26` (complexity bounds) | CONFORMANT (initial, defensible bounds — not yet security-reviewed against a real adversarial-policy corpus, flagged for revisit alongside the Decision Engine) | `MAX_CONDITION_NODES`/`MAX_CONDITION_DEPTH`/`MAX_GATES`/`MAX_RULES` in `validation.py` |
| `SEC-7.23`/`7.24` (policy security and governance) | CONFORMANT | `Permission.POLICY_MANAGE` administrative-only; `test_operational_scope_does_not_grant_policy_manage` / `test_administrative_scope_grants_policy_manage` |
| Invariant 12 (audit-before-effect) | CONFORMANT | `test_create_and_activate_persists_and_audits` (real Postgres) — activation and its `REQUIRED` `POLICY_ACTIVATED` audit event share the same unit of work; an audit failure rolls back the whole activation (same mechanism proved directly in Foundation-008, reused unmodified here, not re-proven redundantly) |
| Foundation-009 discovery question 6/8 (no ambiguous active state, including under concurrency) | CONFORMANT | `test_partial_unique_index_rejects_two_active_rows_direct_insert` (direct DB-level proof) + `test_concurrent_activation_for_the_same_applicability_one_wins_one_conflicts` (deterministic, barrier-synchronized real-Postgres race — see methodology correction above) |
| Part V §5.36 (staged/shadow/simulation policy states) | DEFERRED | Two-state lifecycle only, matching the spec's own deferred status |

## Validation (at closure)

138/138 tests pass (37 new: 31 unit + 6 real-Postgres integration), ruff clean repo-wide, `compileall` clean, `alembic check` confirms zero unintended drift beyond the new `policies` table, `git diff --check`'s single flagged line (`core/audit/enums.py:18`) is the known `core.autocrlf=true` false-positive — confirmed via `cat -A` to show a clean LF line ending, not a real whitespace defect (same documented quirk as prior foundations).

**mypy:** `core/`, `infrastructure/`, and `apps/` are clean (0 errors) under this foundation's changes. Project-wide `mypy .` reports 73 errors, all `no-untyped-def`-class findings in `tests/`; a `git stash` comparison against the pre-Foundation-009 `main` confirmed 56 of these are pre-existing (present in Foundation-008's own test files, e.g. `test_evidence_result_service.py`), not a regression. This foundation's new test files add 17 more findings of that same pre-existing category (missing return-type/parameter annotations on pytest functions) — consistent with, not a departure from, the project's established (if informally so) practice of not holding `tests/` to `strict = true` in practice.

## Files changed

`core/audit/enums.py` (added `POLICY_ACTIVATED`), `core/security/authorization.py` (added `Permission.POLICY_MANAGE`, administrative-only), `infrastructure/database/models/__init__.py` (registered `PolicyRecord`) — all additive edits to existing Foundation-004/006 files. New: `core/policy/{__init__,enums,condition,models,canonicalization,validation,exceptions,repository,service}.py`, `core/evidence_result/schema_catalog.py`, `infrastructure/database/models/policy.py`, `infrastructure/database/repositories/policy.py`, one Alembic migration, 6 new test files (`tests/unit/test_policy_{condition,canonicalization,validation,service,authorization}.py`, `tests/integration/test_policy_persistence.py`).

## Commits

Implementation: `d641e90`.
Closure record: this commit.

## Remaining deferred/held capabilities (unaffected by this foundation)

- **Rate Limiting / Abuse Prevention (`SEC-7.32`/`REL-10.16`)** — remains explicitly **HELD**, unchanged since Foundation-006, through Foundations 007, 008, and now 009. To be reassessed as a candidate future foundation now that 009 is closed.
- Credential lifecycle idempotency gap (flagged in `FOUNDATION-007.md`) — unaddressed, unaffected by this foundation.
- Evidence-result deletion/tombstone enforcement (flagged `DEFERRED` in `FOUNDATION-008.md`) — unaffected.
- Policy complexity bounds (`DEC-5.26`) are an initial, defensible mapping, not yet security-reviewed against a real adversarial-policy corpus — flagged above, same posture as Foundation-008's classification-mapping caveat.

## What depends on this next

The future Decision Engine (Part V §5.18–5.23) consumes `PolicyService.get_active()`/`get()` to obtain the applicable immutable policy for a tenant and assurance level, and `EvidenceResultRepository.list_for_session()` (Foundation-008) to obtain the evidence set — then, and only then, evaluates `conditions`/`gates`/`rules` against that evidence to produce a `VERIFIED`/`REJECTED`/`REVIEW_REQUIRED`/`INCONCLUSIVE` outcome. Foundation-009 establishes the authoritative, immutable policy store; it does not evaluate policies or produce verification decisions.
