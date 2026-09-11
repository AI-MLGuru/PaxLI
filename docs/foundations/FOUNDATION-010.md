# Foundation-010 — Rate Limiting / Abuse Prevention

**Status:** CLOSED
**Closed:** 2026-09-10
**Depends on:** Foundation-006 (`AuthenticatedPrincipal`, generic-authentication-failure precedent, `Permission`), Foundation-007 (bounded-timeout/guarded-operation pattern, reused for the limiter's own DB call), Foundation-009 (atomic-upsert-as-concurrency-authority precedent, barrier-synchronized concurrency test methodology)
**Normative basis:** Part VI §6.23 (Rate Limiting), Part VII §7.32 (Abuse Prevention), Part X §10.16 (Overload and Backpressure)

## Identity

`SEC-7.32`/`REL-10.16` had been carried as an explicitly `HELD` capability since Foundation-006, through Foundations 007, 008, and 009 — deliberately not implemented until the surrounding foundations that would give it real shape (tenant/credential identity, audit infrastructure, the reliability wrapper pattern) were in place. Foundation-010 closes that gap: an admission-control layer that can reject a request before it consumes expensive resources, structurally incapable of producing or influencing a verification outcome.

> **Rate limiting is an admission-control mechanism, never a verification decision mechanism.** No exception handler, fail-open path, or scope-evaluation function anywhere in `core.rate_limit` imports `VerificationStatus` or `EvidenceResultStatus`, and nothing translates a `RateLimitExceededError` into either.

## Scope boundary (as approved, verified against the implementation)

**In scope, delivered:** fixed-window rate limiting scoped to tenant, credential, and operation; a narrow pre-authentication network-source throttle on the credential-lookup path only; atomic PostgreSQL-backed admission counters; most-restrictive-wins multi-scope evaluation; fail-open/fail-closed semantics by endpoint class; the `429`/`RATE_LIMITED`/`Retry-After` API contract; dedicated `RateLimitMetrics`; request-path wiring into the live API.

**Explicitly out of scope, untouched:** Redis (left exactly as found — an orphaned, unused `docker-compose.yml`/`.env.example` entry, never activated); tenant-configurable limits (static config only); a general network-source dimension beyond the one pre-auth call site; sliding-window/token-bucket algorithms; worker/provider/storage capacity quotas; any GET/read endpoint (no read route acquired rate limiting); the Decision Engine, condition/gate/rule evaluation, or any verification-outcome semantics.

## Key architectural decisions (approved across discovery, implementation-plan, and phase reviews)

1. **PostgreSQL over Redis or in-process counters.** In-process counters are dishonest under horizontal scale-out (each replica gets an independent budget); Redis would be a new operational dependency adopted "because conventional," contradicting the project's existing dependency discipline, and the orphaned compose entry was explicitly not treated as license to activate it. Postgres was already authoritative, transactional, and tenant-scoped.
2. **Fixed window, not sliding window or token bucket.** Deterministic, cheap, testable; the accepted ~2x boundary-burst tradeoff is documented as a deliberate v1 engineering choice, not a conformance gap.
3. **Atomic single-statement upsert** (`INSERT ... ON CONFLICT DO UPDATE ... RETURNING`), window computed server-side from Postgres's own `now()` — never application-server time, so multiple API replicas never disagree about window boundaries. No select-then-check-then-update anywhere.
4. **The limiter's admission transaction is independent of the caller's request transaction.** `PostgresRateLimiter` takes a session *factory*, never an injected session — structurally impossible to share the caller's session. A consumed slot survives the caller's own later business-transaction rollback (proved directly against real Postgres).
5. **Pre-auth network-source throttle**, added during the implementation-plan review after identifying a real gap: without it, `authenticate_bearer()`'s credential lookup (including the scrypt hash comparison) would run unthrottled for every attempt, leaving exactly the "credential attacks, enumeration" surface `SEC-7.32`'s own preamble names. Wired as a sub-dependency of `get_principal`, guaranteeing it resolves before `authenticate_bearer` is ever called. HMAC-SHA256 keyed by a dedicated secret (never the credential-hashing key, never the evidence-encryption key) — the raw IP never reaches `core.rate_limit` or persistence.
6. **`evaluate_admission` catches only `RateLimiterUnavailableError`, never bare `Exception`** — a correction made during Phase 1 review, stricter than the original implementation plan. Catching broadly would have let an unrelated programming defect (a malformed scope key, a bug) be silently absorbed as "limiter unavailable" and fail-opened past. Tested directly.
7. **Fail-open means bypassing the limiter only, never authentication or authorization.** `evaluate_admission` has no knowledge of either and calls neither; a limiter failure on an operational endpoint continues past that one exhausted-or-unreachable rule, but authentication/authorization are separate calls entirely, structurally un-bypassable by this code path. Tested directly with a spy that proves `authenticate_by_id` is never called once the pre-auth scope is exhausted, and a separate test proving fail-open still requires authentication/authorization to succeed.
8. **Most-restrictive-wins**, deliberately primitive: every configured `(rule, scope_key)` pair is checked in order; the first exhausted scope rejects the whole request. No weights, no priority, no conflict resolution, no tenant-authored rules — avoids duplicating Foundation-009's policy-governance machinery for what is an operational concern.
9. **Static, environment-driven configuration**, not tenant-configurable — avoids building a second policy-governance layer for admission control.
10. **A dedicated `RateLimitMetrics`**, not a reuse of `core.reliability.metrics.ReliabilityMetrics` — that class's shape (success/timeout/unavailable/degraded/circuit state) is built for per-dependency outcomes, not per-request-scope rejection counts; reusing it would have been a shape mismatch.

## Two real findings surfaced during real-infrastructure testing, not left latent

1. **Connection pool exhaustion, not an atomicity defect.** An early version of the decisive concurrency test used 20 simultaneous attempts and produced misleading `RateLimiterUnavailableError` timeouts on the tail requests — traced to the shared engine's connection pool (`pool_size=5 + max_overflow=10 = 15`) being exceeded by a deliberately-synchronized burst, not a flaw in the atomic upsert. Right-sized to 8 concurrent attempts against a limit of 3, comfortably within pool capacity while still proving genuine overlap.
2. **Transient host/Docker resource contention, not a code defect.** During Phase 4 validation, the same concurrency test intermittently timed out — including, decisively, on a single *non-concurrent* call in the same run, which ruled out any relationship to concurrency or row-level locking. Traced conclusively via `docker stats` to an unrelated container on the host consuming 116%+ CPU at that moment, while `averiq-postgres-1` itself sat idle at 0% CPU. Not a Foundation-010 defect; the test's docstring now documents the correct diagnostic method (check whether an uncontended single call is also slow) so a future flake here is triaged correctly rather than re-litigated. Stable across repeated runs once the interfering process quieted down.

## Requirement conformance

| Requirement | Status | Evidence |
|---|---|---|
| `API-6.23.1`–`6.23.4` (429, stable code, `Retry-After`, non-leaking) | CONFORMANT | `rate_limit_exceeded_exception_handler` in `main.py`; `test_rate_limiting.py`'s 429-contract tests |
| `API-6.23.5` (tenant isolation) | CONFORMANT | `authenticated_rules` scopes on `tenant_id` independently of `credential_id`; scope-isolation tests |
| `API-6.23.6` / `SEC-7.32.5` (never becomes a verification outcome) | CONFORMANT | Structural: no import of verification/evidence-result status types anywhere in `core.rate_limit`; `test_a_rate_limited_request_creates_no_verification_session` (zero `VerificationSessionRecord` rows after a 429) |
| `SEC-7.32.1`/`7.32.2` (prevent unauthorized consumption, preserve isolation/availability) | CONFORMANT | Fail-open on operational endpoints preserves availability under limiter outage; fail-closed on credential-management preserves the abuse boundary |
| `SEC-7.32.3` (follow Part VI) | CONFORMANT | Same `429`/`RATE_LIMITED`/`Retry-After` contract |
| `SEC-7.32.4` (repeated auth failures SHOULD be observable) | CONFORMANT, evidenced as two independent facts, not one combined claim | Foundation-006's existing `AUTHENTICATION_FAILED` audit event (unchanged) makes failures *observable*; Foundation-010's pre-auth throttle makes attempts *bounded before the expensive credential-lookup path runs* — proved by a spy showing `authenticate_by_id` is never called once the pre-auth scope is exhausted |
| `REL-10.16.1`–`10.16.3` (capacity boundaries, no uncontrolled exhaustion, load shedding doesn't corrupt state) | CONFORMANT for HTTP request-rate; N/A for worker/provider capacity (not yet built) | Real-Postgres concurrency test: at most `limit` admitted under genuine contention, every attempt durably counted, no lost updates |
| Tenant-configurable limits | DEFERRED | Static config only, matching the approved decision |
| General network-source dimension | DEFERRED | Narrowly scoped to the one pre-auth call site |
| Sliding-window/token-bucket precision | DEFERRED, accepted tradeoff | `~2x` boundary-burst behavior documented, not silently absorbed |
| Redis activation | N/A — explicitly not done | Compose/`.env.example` entries left exactly as found, orphaned |

## Validation (at closure)

178/178 tests pass (38 new: 23 unit, 8 real-Postgres integration, 7 API-level contract/security tests), ruff clean, mypy clean (`core/`, `infrastructure/`, `apps/` — 128 source files), `compileall` clean, `alembic check` confirms zero unintended drift beyond the new `rate_limit_windows` table, `git diff --check` clean (one CRLF-autocrlf false-positive note, same documented quirk as prior foundations). Full suite and the decisive concurrency test independently re-confirmed stable across multiple runs once transient host resource contention (see findings above) had cleared.

## Files changed

**Phase 1 (domain):** `core/rate_limit/{__init__,enums,models,exceptions,limiter,keys,evaluation,metrics}.py`, 4 unit test files.
**Phase 2 (persistence):** `infrastructure/database/models/rate_limit_window.py`, `infrastructure/database/models/__init__.py` (registration), `infrastructure/rate_limit/{__init__,postgres_limiter,pruning}.py`, one Alembic migration, 1 integration test file.
**Phase 3 (request-path wiring):** `apps/api/paxli_api/config.py` (rate-limit settings), `apps/api/paxli_api/dependencies.py` (`get_rate_limiter`, `enforce_pre_auth_admission`, `get_principal` chaining, `enforce_rate_limit`), `apps/api/paxli_api/main.py` (`RateLimitExceededError` handler), `apps/api/paxli_api/routers/{verification_sessions,evidence,management/credentials}.py` (rate-limit calls on `create_session`, `store_upload`, `issue_credential`/`rotate_credential`/`revoke_credential` — no GET route touched), `infrastructure/rate_limit/{network_source,rules}.py`, `tests/conftest.py` (`AlwaysAllowRateLimiter` override for the shared `api_client` fixture), 1 contract/security test file.
**Post-Phase-3 correction:** `tests/integration/test_rate_limit_persistence.py` (concurrency test docstring/value correction after the host-contention finding).

## Commits

Phase 1: `230413f`. Phase 2: `67aa00e`. Phase 3: `d27a50b`. Test correction: `c7d37cf`. Closure record: this commit.

## Remaining deferred/held capabilities (unaffected by this foundation)

- Credential lifecycle idempotency gap (flagged in `FOUNDATION-007.md`) — unaffected.
- Evidence-result deletion/tombstone enforcement (flagged `DEFERRED` in `FOUNDATION-008.md`) — unaffected.
- Policy complexity bounds review (flagged in `FOUNDATION-009.md`) — unaffected.
- Tenant-configurable rate limits, a general network-source dimension, sliding-window/token-bucket algorithms, worker/provider/storage capacity quotas — all explicit Foundation-010 non-goals, not silently dropped.
- Redis remains orphaned, unused scaffold — a candidate for a future hygiene task (removal), not a dependency this or any foundation should build on without fresh justification.

## What depends on this next

Nothing yet — this is a protective/operational foundation, not a dependency of the Decision Engine or any evidence/policy work. Per the user's own framing at foundation selection: 002–010 now form the complete infrastructure base (session, evidence/storage, audit, reliability primitives, security/data-protection, reliability integration, evidence results, policy governance, abuse prevention) the Decision Engine will consume. The next step, per direction already given, is a full 002–010 specification/conformance gap review against Parts II–XI before opening Decision Engine work.
