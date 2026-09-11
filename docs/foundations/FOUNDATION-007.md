# Foundation-007 — Reliability Integration & Operational Observability

**Status:** CLOSED
**Closed:** 2026-09-10
**Depends on:** Foundation-002 (sessions), 003 (evidence/storage), 004 (audit), 005 (reliability primitives), 006 (security)
**Normative basis:** Part X — Reliability & Operations (`REL-*`)

## Identity

Foundation-005 built a complete, unit-tested reliability library
(`core/reliability/`: retry+backoff+jitter executor, circuit breaker,
dependency health check, failure taxonomy, in-memory metrics) that was
never actually called by the running application — every real PostgreSQL
and MinIO call site made direct, unprotected calls with no timeout, no
retry, no circuit breaker. Foundation-007 closes that gap: it wires the
existing primitives into the two real dependencies, replaces the naive
`/ready` check with genuine per-dependency health semantics, and adds the
structured logging and reliability metrics Part X requires and that
previously didn't exist at all. `core/reliability/` itself was not
modified.

## Scope boundary (as approved)

**In scope:** PostgreSQL and MinIO reliability wiring, `/ready` health
semantics, structured logging (`structlog`, finally consuming the
previously-unused `Settings.log_level`), periodic reliability-metrics
logging.

**Explicitly out of scope, untouched:** `core/reliability/`,
`core/verification/orchestrator.py`, `VerificationStatus`/session
lifecycle-decision semantics, Decision Engine, Part IV workflow
implementation, rate limiting/backpressure (`SEC-7.32`/`REL-10.16`, still
HELD from Foundation-006), audit-integrity, evidence deletion/retention,
workers, queues, webhooks, and any new external observability
infrastructure (no `/metrics` endpoint, no Prometheus/OpenTelemetry/Jaeger).

## Requirement conformance

| Requirement | Status | Evidence |
|---|---|---|
| REL-10.8.1–10.8.4 (bounded timeouts) | CONFORMANT | Commit bounded (5s); MinIO GET/PUT/DELETE bounded |
| REL-10.9.1–10.9.4 (bounded, policy-controlled retry) | CONFORMANT for MinIO; N/A for commit (zero-retry is the deliberate policy) | `tests/unit/test_dependency_policies.py` |
| REL-10.9.5 (no duplicate authoritative state from retry) | CONFORMANT for MinIO (proven); **partial gap for non-idempotent Postgres writes** — see Known Gaps | `tests/contracts/reliability/test_minio_retry_safety.py` |
| REL-10.10.1–10.10.4 (circuit breaker) | CONFORMANT | `tests/unit/test_dependency_policies.py` |
| REL-10.11.1–10.11.3 (dependency health) | CONFORMANT | `/ready` checks Postgres + MinIO via `check_dependency()`; live-verified against a killed MinIO container |
| REL-10.12.1–10.12.3 (liveness/readiness distinction) | CONFORMANT | `/health` unchanged (liveness only); `/ready` dependency-aware; neither leaks internal details |
| REL-10.24.1–10.24.3 (observability) | CONFORMANT | `dependency_call` / `reliability_metrics` structured events |
| REL-10.25.1–10.25.3 (structured logging, no sensitive content) | CONFORMANT | `tests/security/test_log_sanitization.py` (dedicated canary tests for this specific surface) |
| REL-10.26.1–10.26.3 (metrics integrity) | CONFORMANT | Reuses `ReliabilitySnapshot`'s existing outcome taxonomy verbatim |
| REL-10.16 (capacity/backpressure) | DEFERRED | Remains held from Foundation-006 by deliberate decision, not oversight |
| REL-10.65.6 (infrastructure failure ≠ `REJECTED`) | CONFORMANT | No code path in this foundation touches `VerificationStatus` |

## Known gap carried forward (not fixed here, not hidden)

> **Credential lifecycle operations (issue/rotate/revoke) have no
> independent idempotency/deduplication mechanism.** If a client — or any
> future automated retry logic — resubmits one of these operations after an
> uncertain-commit outcome (the same class of failure this foundation
> proved is unsafe to auto-retry at the reliability layer), a duplicate
> credential could be issued, or a rotation/revocation could be applied
> twice. This is not a Foundation-007 defect: it's an application-layer gap
> in Foundation-006's credential service that Foundation-007's PostgreSQL
> commit-safety analysis surfaced. It must be closed — with an
> `Idempotency-Key`-style mechanism matching what session creation and
> evidence upload already have — **before** any automated retry or
> client-facing retry guidance is introduced around credential management
> endpoints.

## Two findings from real infrastructure testing (not predicted by design review alone)

1. The MinIO Python SDK performs its own internal urllib3-level retries
   with backoff. A fully unreachable MinIO doesn't fail fast — it exceeds
   the health-check timeout and classifies as `TIMEOUT`/`DEGRADED` rather
   than a clean `UNAVAILABLE`. `/ready`'s ready-state set was tightened to
   `HEALTHY`-only as a result (fail closed on the ambiguity), confirmed by
   killing the MinIO container mid-session and observing the incorrect
   `ready` response before the fix.
2. The module-level async SQLAlchemy engine is event-loop-bound; tests
   exercising it across multiple async test functions could leave a stale
   pooled connection that broke a later, unrelated test's `/ready` check
   against a genuinely healthy database. Fixed with an explicit
   pool-disposal test fixture; documented in
   `tests/integration/test_dependency_reliability.py` rather than
   silently worked around.

## Validation (at closure)

81/81 tests pass (14 new), ruff/mypy/compileall clean, `git diff --check`
clean, `alembic check` confirms zero schema drift (this foundation has no
database impact). Verified live against real PostgreSQL and MinIO
containers.

## Files changed

`apps/api/paxli_api/main.py`, `infrastructure/database/session.py`,
`infrastructure/storage/minio.py` (modified);
`infrastructure/reliability/{__init__,_shared,postgres_policies,minio_policies,dependency_health}.py`,
`infrastructure/observability/{logging,reliability_logging}.py` (new);
5 new test files, 1 test updated for the intentional `/ready` contract
change (`tests/unit/test_health.py`).

## Commits

`73533c2`, `7c2bd50`, `fd8e433` (Foundation-006 closure work), `0ade0d5`
(Foundation-007 implementation).
