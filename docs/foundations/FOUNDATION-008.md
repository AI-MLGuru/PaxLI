# Foundation-008 — Evidence Result Model & Persistence

**Status:** CLOSED
**Closed:** 2026-09-10
**Depends on:** Foundation-002 (sessions), 004 (audit), 006 (security — `KeyProvider`, classification, tenant isolation pattern), 007 (reliability wiring, reused automatically via the shared unit of work)
**Normative basis:** Part III — Evidence Semantics (`EVD-*`), cross-referenced against Part II Invariants 03 & 06, Part V (Decision Engine's evidence-consumption contract), Part VII/XI (security/privacy)

## Identity

Foundation-003 built evidence *capture* storage — raw selfie/document/liveness uploads (`core/evidence/`). Part III's "Evidence" is a distinct concept: a processing component's *interpreted result* (a face-match score, an OCR extraction), which had no data model or persistence anywhere in the codebase before this foundation. Foundation-008 closes that gap: `core/evidence_result/` and its persistence layer, deliberately kept separate from `core/evidence/` rather than extending it, so the Capture/Result distinction is structural in the codebase, not just documented.

## Scope boundary (as approved)

**In scope:** `EvidenceResult` domain model, Part III status taxonomy, per-type result-payload schemas, provenance/lineage/integrity fields, persistence (`evidence_results` table, repository, migration), tenant isolation, classification-driven encryption of highly-sensitive payloads, immutability/supersession semantics, audit integration (`EVIDENCE_RESULT_CREATED`/`EVIDENCE_RESULT_SUPERSEDED`), retention metadata.

**Explicitly out of scope, untouched:** `core/evidence/`, `core/verification/orchestrator.py`, `core/decision/`, `core/face/`, `core/document/`, `core/liveness/`, `core/quality/`, `core/risk/`, `core/learning/`, `apps/` (no router, no dependency-injection wiring — nothing produces evidence results yet), Decision Engine, policy evaluation, model runtime, deletion/tombstone enforcement.

## Two refinements made during implementation planning (before code, confirmed by the user)

1. **No dedicated audit event for rejected/invalid submissions.** `EVD-3.24.4` ("validation failures MUST be observable and auditable according to applicable audit requirements") is satisfied through the *normal* `EVIDENCE_RESULT_CREATED` event when a caller follows up with a safety-net `INCONCLUSIVE` result — not a second audit trail for an attempt that never touched governed state (Invariant 12 §12.16's carve-out for internal computations with no independent significance applies).
2. **`retention_until` column only, no tombstone table.** A full `evidence_result_deletions` subsystem with zero application code touching it was judged premature infrastructure (Part IX `DEF-9.21.1`); the full tombstone mechanism is deferred to whenever deletion enforcement becomes its own foundation, built as one cohesive unit rather than split across two.

## Requirement conformance

| Requirement | Status | Evidence |
|---|---|---|
| `EVD-3.4.1-3.4.3` (stable, independent identity) | CONFORMANT | `EvidenceResult.id`; `test_evidence_result_model.py` |
| `EVD-3.6.1-3.6.5`, Invariant 03 §3.1-3.4 (closed status vocabulary) | CONFORMANT | Pydantic-enforced enum rejection; `test_evidence_result_status_is_a_closed_vocabulary` |
| Constitutional: evidence status ≠ decision outcome | CONFORMANT | `test_evidence_result_status_does_not_share_values_with_verification_status` — structural, not just documented |
| `EVD-3.8`, `3.15` (provenance, model references) | CONFORMANT | `producer`/`producer_version`/`model_reference` fields, round-tripped in `test_evidence_result_service.py` |
| `EVD-3.9.1-3.9.5`, Invariant 06 §6.2/6.5 (integrity) | CONFORMANT | `integrity_reference` server-computed, deterministic for identical content — `test_integrity_reference_is_server_computed_and_deterministic` |
| `EVD-3.10.1-3.10.4`, Invariant 06 §6.1/6.6 (immutability) | CONFORMANT | No `update()` in the repository Protocol; `supersede()` creates a new row — `test_supersede_creates_a_new_row_and_never_mutates_the_original` (unit) + real-Postgres equivalent |
| `EVD-3.17` (lineage) | CONFORMANT | `parent_evidence_result_ids`, `supersedes_id` |
| `EVD-3.24.1-3.24.4` (invalid evidence) | CONFORMANT | `InvalidEvidenceResultError` rejects before persistence; `test_invalid_result_payload_persists_nothing_and_audits_nothing` |
| `EVD-3.26/3.27` (deletion, tombstones) | DEFERRED | `retention_until` only — refinement #2; consistent with the standing Foundation-006/007 held decision |
| `EVD-3.29.1-3.29.6` (tenant/access boundaries) | CONFORMANT | `test_cross_tenant_get_returns_none` (real Postgres) |
| `EVD-3.30.1-3.30.5` (Decision Engine contract) | CONFORMANT for the contract; N/A for consumption | Read methods exist for a future Decision Engine; nothing consumes them yet |
| `EVD-3.33` (Liveness, external-provider evidence) | DEFERRED | Types defined, nothing produces them — matches the spec's own `TARGET: v1.1` |
| `SEC-7.17`, `PRV-11.6` (biometric protection) | CONFORMANT | `FACE_EMBEDDING` classified `HIGHLY_SENSITIVE`, encrypted at rest via the existing `KeyProvider`; canary embedding absent from raw stored bytes — `test_highly_sensitive_result_is_encrypted_at_rest_and_round_trips` |
| Invariant 12 (audit-before-effect) | CONFORMANT | `test_required_audit_failure_leaves_no_evidence_result_row` (real Postgres) |

## A real bug caught by testing, not design review

SQLAlchemy's `JSON` column type stores a Python `None` as the JSON literal `null` by default, not SQL `NULL` — this silently defeated the `result_json IS NULL` half of the payload-representation CHECK constraint until `JSON(none_as_null=True)` was applied. Found by writing the constraint-violation test against real Postgres, not by reasoning about the design.

## Validation (at closure)

103/103 tests pass (22 new), ruff/mypy/compileall clean, `git diff --check` clean, `alembic check` confirms zero unintended drift beyond the new `evidence_results` table.

## Files changed

`core/audit/enums.py` (added `EVIDENCE_RESULT_CREATED`/`EVIDENCE_RESULT_SUPERSEDED`), `infrastructure/database/models/__init__.py` (registered new model) — both additive edits to existing Foundation-004/006 files. New: `core/evidence_result/{__init__,enums,models,schemas,exceptions,classification,repository,service}.py`, `infrastructure/database/models/evidence_result.py`, `infrastructure/database/repositories/evidence_result.py`, one Alembic migration, 4 new test files.

## Commit

`4c1232d`.

## What depends on this next

The future Decision Engine (Part V) consumes `EvidenceResultRepository.list_for_session()`/`list_for_session_by_type()` to build its `evidence_set` input. Policy governance (schema for `DEC-5.14`'s `EvidenceCondition`) should follow this foundation, not precede it, since it needs real `evidence_type`/field names to reference — confirmed during discovery, unchanged by implementation.
