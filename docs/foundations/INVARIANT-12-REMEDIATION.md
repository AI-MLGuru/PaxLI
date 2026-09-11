# Invariant-12 Remediation — Audit Completeness Gap Closure

**Status:** CLOSED
**Closed:** 2026-09-11
**Depends on:** Foundation-004 (audit infrastructure), Foundation-006 (security/tenant isolation), Foundation-007 (independent-transaction/bounded-timeout pattern), Foundation-008 (evidence results), Foundation-009 (policy governance), Foundation-010 (independent-transaction precedent, `PostgresRateLimiter`)
**Normative basis:** Part II Invariant 12 (Audit Completeness), specifically §12.5 (event identity/idempotency), §12.10 (failed actions), §12.17 (audit retrieval)

## Identity

Not a numbered foundation — deliberately. This closes four bounded, specific gaps identified during the Part II → Invariant 12 deep-pass audit, without reopening or renumbering Foundations 002–010. The architectural history stays exactly as it was: 002 through 010 closed, then this remediation, then the Part II re-audit resumes.

## Why this came before Part III

Invariant 12 governs the audit-before-effect contract every other invariant and foundation depends on. The deep pass found the core mechanism sound (ordering, durability, failure-blocks-effect, privacy sanitization, tenant isolation all independently proven) but surfaced four concrete, bounded gaps — all classified `NONCONFORMANT (non-blocking)` for the current release, but explicitly flagged as **must-fix before the Decision Engine**, since that work will multiply the number of governed state transitions built on this exact contract.

## The four remediations

**1. Idempotency + audit dedupe** (`156c1ae`). Extended the existing `Idempotency-Key` pattern (already proven for `VerificationSessionService.create()`) to policy activation, evidence-result creation, and credential issue/rotate. A retried request now resolves to the same logical outcome instead of silently creating a second real activation, evidence result, or credential. Idempotency is **operation-scoped**, not merely tenant-scoped — the stored key is composed as `"<operation>:<caller-key>"` so a caller reusing the same raw key across two different operations sharing one table (e.g. `issue` vs `rotate`) can never collide. Credentials are a deliberate, explicit exception: since the raw secret exists only once and can never be recovered from the stored one-way hash (SEC-7.9.9), a same-key replay raises `IdempotentReplayWithoutSecretError` (409) rather than returning a fabricated success that silently omits the secret the caller needs.

**2. Material governed-action failure auditing** (`c567794`). Established the rule: *a material, externally initiated governance/authorization action that fails after authentication is auditable, not just its successes.* Two new event types (`POLICY_ACTIVATION_FAILED`, `CREDENTIAL_OPERATION_FAILED`). `InvalidPolicyError`/`InvalidEvidenceResultError` deliberately remain outside this boundary, governed by the pre-existing Part III/internal-computation carve-out (Foundation-008 refinement #1) — a principled distinction, not an ever-growing exception list. Credentials (a live router) get a new global exception handler mirroring the existing `AUTHENTICATION_FAILED`/`AUTHORIZATION_DENIED` pattern exactly; this also fixed a latent gap where `rotate_credential` had no handling at all for an already-expired-credential conflict (an unhandled 500). Policy (no router exists yet) got **Option 2**: `PolicyService` now accepts an optional `IndependentAuditRecorder` — a narrow Protocol, not a concrete SQLAlchemy type, keeping `core/` infrastructure-agnostic, the same dependency-inversion shape as `KeyProvider`/`RateLimiterProtocol`. On a `PolicyActivationConflictError`, it records the failure through a genuinely independent transaction (`infrastructure/audit/independent.py`), never the caller's own aborted one. If that independent write itself fails, the original conflict still propagates unmasked — logged, never replaced by a fabricated success/failure state (explicit decision, carried through exactly as specified).

**3. Governance audit retrieval** (`aa0c272`). New `GET /v1/management/audit-events`. The existing session-scoped endpoint could never surface `POLICY_ACTIVATED`, any `CREDENTIAL_*` event, or either new `*_FAILED` event — all durably recorded, none retrievable except by direct database access. Tenant is always the authenticated principal's own; there is no `tenant_id` parameter, so cross-tenant retrieval is structurally impossible, not just policy-denied. Filters: `event_type`, `actor_id`, `occurred_after`/`before`; results always bounded (default 100, hard cap 500).

**4. Public-entry-point audit ordering** (`9e4088f`). The deep pass flagged that sessions, evidence-capture, and credentials bake their audit call into the *router* rather than the domain service (unlike evidence-results and policy, where it's inside the service) — a structural risk, not a live gap, since every current router call site was already faithful. Rather than refactor three services for architectural symmetry (rejected as unnecessary churn for this bounded pass), added the missing "required-audit-failure leaves no orphaned row" tests at the actual public entry points for evidence-capture upload and credential issuance — sessions already had this. If a future change ever drops or reorders one of these audit calls, the test catches it immediately instead of the gap surfacing only in a future audit review.

## Updated Invariant 12 conformance (supersedes the deep-pass findings)

| Finding from the deep pass | Status now |
|---|---|
| #1 Missing dedupe for policy/evidence-result/credentials | **CONFORMANT** — remediation 1 |
| #2 Failed governed actions not audited | **CONFORMANT** — remediation 2 |
| #3 Retrieval only session-scoped | **CONFORMANT** — remediation 3 |
| #4 Router/service audit-call placement | **NEEDS EVIDENCE → hardened**, not refactored — remediation 4 (explicit, deliberate choice: tests over churn) |
| Deletion/retention interaction (12.61/12.62) | **N/A, unchanged** — still correctly blocked on the separate Invariant 06 deletion decision, not touched by this remediation |
| Audit integrity mechanism (12.17), no DB-level backstop | **CONFORMANT, unchanged** — still the weakest of the permitted mechanisms (absence-of-update-code-path, not a hash/signature/DB grant), still a LOW-severity hardening item, not addressed here (out of this remediation's bounded scope) |

**Blocking Invariant-12 violations: none, before or after.** This remediation converts four `NONCONFORMANT (non-blocking)` findings to `CONFORMANT` and hardens one `NEEDS EVIDENCE` finding with regression tests, closing everything the deep pass flagged as must-fix-before-Decision-Engine.

## Validation (at closure)

197/197 tests pass (28 new across the four phases: idempotency unit + real-Postgres integration tests for policy/evidence-result, credential idempotency contract tests, failure-audit unit + real-Postgres integration tests for policy's Option 2, credential `CredentialStateError` unit + contract tests, management audit-retrieval contract tests, public-entry-point ordering tests), ruff clean, mypy clean (`core/`/`infrastructure/`/`apps/`, 131 source files), `compileall` clean, `alembic check` zero drift beyond the three additive idempotency-key migrations, `git diff --check` clean throughout (including renormalizing several files that had pre-existing CRLF line-ending contamination already baked into HEAD from before this session's line-ending discipline caught up — a genuine, in-scope hygiene fix on files this remediation legitimately touched, not scope creep).

## Files changed (by phase)

**Phase 1:** `core/policy/{service,repository}.py`, `infrastructure/database/{models,repositories}/{policy,evidence_result,credential}.py`, `core/evidence_result/{service,repository}.py`, `core/security/{credentials,exceptions}.py`, `apps/api/averiq_api/{main,routers/management/credentials}.py`, 3 new migrations, 8 test files.
**Phase 2:** `core/audit/enums.py`, `core/policy/service.py`, `core/security/{credentials,exceptions}.py`, `apps/api/averiq_api/{main,routers/management/credentials}.py`, new `infrastructure/audit/{__init__,independent}.py`, 4 test files.
**Phase 3:** `core/audit/{repository,service}.py`, `infrastructure/database/repositories/audit_event.py`, new `apps/api/averiq_api/routers/management/audit.py`, `apps/api/averiq_api/main.py`, 1 new test file.
**Phase 4:** `tests/contracts/security/test_audit_ordering.py`.

## Commits

Phase 1: `156c1ae`. Phase 2: `c567794`. Phase 3: `aa0c272`. Phase 4: `9e4088f`. Closure record: this commit.

## What's next

Per the approved sequence: Part II → Invariant 12 remediation (this) → **Invariant 06 deletion decision** → contract-test traceability decision (§2.21's file-organization gap) → scaffold cleanup (`core/decision/`, `core/document/`, `core/face/`, `core/liveness/`, `core/learning/` — orphaned pre-normative code, zero references) → Decision Engine/TBD complexity clarification (Part II §10.10) → Part III final conformance → Part IV → ... → Decision Engine, only once the full Part II baseline is clean.
