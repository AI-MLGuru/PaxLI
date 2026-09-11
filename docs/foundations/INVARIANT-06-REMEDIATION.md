# Invariant-06 Remediation — Closure Record

**Scope:** Part II Invariant 06 §6.8-6.11 (deletion), Part III §3.26-3.28
(Evidence Deletion, Evidence Tombstones, Evidence Retention), Part XI
§11.29-11.30 and §11.35 (Data Deletion, Deletion and Tombstones, Erasure
Interaction) — applied to the two domains in scope: raw evidence capture
(`core/evidence/`) and interpreted evidence results (`core/evidence_result/`).

**Explicitly out of scope** (per the approved discovery/decision/plan,
unchanged throughout remediation): retention scheduler, worker/queue,
automatic purge, distributed transaction framework, policy/credential
deletion, Decision Engine, a generalized deletion abstraction beyond these
two domains, and any HTTP-level exposure of retention-expired listings.

## Architecture

A two-phase, two-transaction tombstone. Each phase is its own
independently-committed unit of work — Postgres and MinIO cannot share a
transaction, so pretending otherwise would let a crash roll back the very
record proving deletion was requested while an already-applied MinIO
delete stayed applied.

```text
PHASE 1 — REQUEST (ambient, request-scoped session)
Validate deletion_basis/basis_reference/authorized_by
        |
Tenant-scoped lookup (404 if absent)
        |
Dependent-row check (409 if blocked -- Phase 6 finding, below)
        |
Tombstone(requested_at) + EVIDENCE_DELETION_REQUESTED audit
        |
COMMIT
════════════════════════════════════════════
Durable deletion intent now exists; no physical
deletion has happened yet.
════════════════════════════════════════════

PHASE 2 — RECONCILIATION (independent session, own commit)
Already executed?  -> return as-is (idempotent no-op)
        |
Evidence row present? -> storage.delete(object_key)  [idempotent, external]
        |
repository.delete_content()  [idempotent DB DELETE]
        |
Required EVIDENCE_DELETED audit (dedupe_key-protected)
        |
mark_tombstone_executed()
        |
COMMIT
```

`executed_at` is the sole authoritative signal that the defined v1
deletion scope (object storage + database content) has been satisfied —
never that deletion was merely requested or attempted. A tombstone with
`requested_at` set and `executed_at` still `NULL` is a truthful,
safely-retryable incomplete state.

## Implementation trace

| Phase | Commit | Content |
|---|---|---|
| 1 — Domain contracts | `855fd97` | `core/deletion/` (`DeletionBasis`, validation), `EvidenceTombstone` / `EvidenceResultTombstone` models (Part III §3.27's `EvidenceDeleted` schema, literally) |
| 2 — Persistence | `91450b1` | `evidence_tombstones` / `evidence_result_tombstones` tables (migration `b3e7f1a94c2d`), repository `get`/`get_tombstone`/`add_tombstone`/`mark_tombstone_executed`/`delete_content`/`list_expired` |
| 3 — Deletion services | `cb26619` | `EvidenceService`/`EvidenceResultService.request_deletion`/`.reconcile_deletion`, `EvidenceDeletionReconciler`/`EvidenceResultDeletionReconciler` Protocols + `infrastructure/deletion/reconciliation.py`, `Permission.EVIDENCE_DELETE` (administrative-only), 4 new `AuditEventType` values |
| 4 — HTTP/API | `375c9d7` | `DELETE`/`GET` on individual evidence, `DELETE /v1/management/evidence-results/{id}`, 410 Gone (flat body, no deletion metadata) vs. ordinary 404, `list_evidence` tombstone exclusion |
| 5 — Real-infrastructure failure injection | `205e222` | 3 approved crash scenarios, each driving the real reconciler through a genuine failure against real Postgres + MinIO |
| 6 — Closure + dependent-row fix | *(this record)* | Re-audit against spec; one genuine gap found and fixed (below) |

## Phase 6 finding: FK dependents with no `ON DELETE` behavior

**Discovery method:** direct reproduction against the real Postgres
baseline re-established at the start of Phase 6 — not inspection, not a
unit test with a fake. Neither Phase 3's nor Phase 5's tests happened to
create a referencing row, so this path had never been exercised.

**The gap:** `evidence_results.source_reference -> evidence.id` and
`evidence_results.supersedes_id -> evidence_results.id` are both foreign
keys with no `ON DELETE` clause (default `RESTRICT`). When a dependent row
exists, `reconcile_deletion()` deletes the MinIO object first (external,
real, unrollback-able), then hits `asyncpg.ForeignKeyViolationError` on
the DB `DELETE`. The DB delete rolls back correctly (no false
`executed_at` — the audit-before-effect guarantee held), but the
tombstone can **never** reach `executed_at` through any number of
retries: every retry hits the identical, deterministic FK violation.
Given `EvidenceResult.source_reference` exists specifically so a
processing component's result can reference its originating evidence,
this is not an edge case — it is the shape every evidence item takes once
any result is produced from it.

**Reproduction evidence (both classes, against real Postgres, before the fix):**

```
RECONCILE FAILED: IntegrityError ... ForeignKeyViolationError:
update or delete on table "evidence" violates foreign key constraint
"evidence_results_source_reference_fkey" on table "evidence_results"

RECONCILE FAILED: IntegrityError ... ForeignKeyViolationError:
update or delete on table "evidence_results" violates foreign key
constraint "evidence_results_supersedes_id_fkey" on table "evidence_results"
```

**Decision (explicit, user-approved):** reject at `request_deletion()`
time rather than relax the FK or let reconciliation get stuck. A blocked
request never creates a tombstone and never touches storage — the
resource stays exactly as it was, and the caller gets an immediate,
actionable `409 DELETION_BLOCKED_BY_DEPENDENTS` instead of a silently
wedged deletion. The FK's `RESTRICT` behavior is deliberately kept as a
defense-in-depth backstop, not weakened.

**Fix:** `EvidenceRepository.has_dependent_evidence_results()` /
`EvidenceResultRepository.has_dependent_evidence_results()` (new,
narrowly-scoped Protocol methods — not a generic query capability),
checked in both services' `request_deletion()` immediately after the
tenant-scoped existence check and before any tombstone is built. New
`DeletionBlockedByDependentsError`, with a global exception handler
(`apps/api/paxli_api/main.py`) mapping it to 409 — the same shape as the
existing `DeletionAlreadyRequestedError` handler.

**Verification (post-fix, real Postgres, both classes):** the identical
reproduction script now reports `CORRECTLY BLOCKED`, confirms the MinIO
object is untouched, and confirms no tombstone was created. Formalized as:
- `tests/integration/test_evidence_deletion_service.py::test_request_deletion_is_blocked_by_a_dependent_evidence_result`
- `tests/integration/test_evidence_deletion_service.py::test_evidence_result_request_deletion_is_blocked_by_dependent_supersession`
- `tests/contracts/security/test_evidence_deletion_api.py::test_delete_evidence_with_dependent_result_is_409`
- `tests/unit/test_evidence_deletion_service.py::test_request_deletion_is_blocked_by_a_dependent_evidence_result`
- `tests/unit/test_evidence_result_deletion_service.py::test_request_deletion_is_blocked_by_a_dependent_supersession`

**Residual, accepted risk:** a race between the dependent check and
`add_tombstone()` — a dependent created in that narrow window — is not
closed by this fix (it would still hit the FK violation deterministically
on retry, same as before the fix, just far less likely). Closing it
completely would require either a single transaction spanning the check
and the tombstone insert with a stronger isolation level, or moving the
check into the database as a trigger/constraint — both judged
disproportionate to the actual risk for v1 and explicitly not pursued
here, consistent with the "smallest coherent change" discipline this
remediation has followed throughout.

## Real-infrastructure evidence chain (Phase 6)

Docker Desktop's daemon was unreachable at the start of this session;
`averiq-postgres-1` and `averiq-minio-1` had both stopped when it came
back. Before any Phase 6 work:

```
docker start averiq-postgres-1 averiq-minio-1
Postgres reachable (direct asyncpg connect)      -- confirmed
MinIO reachable (200 on /minio/health/live)       -- confirmed
alembic upgrade head                              -- clean, b3e7f1a94c2d
full suite                                        -- 266/266, 0 skipped
full suite (repeat)                               -- 266/266, 0 skipped
```

After Phase 5's 3 new tests: 269/269 twice. After the Phase 6 fix and its
5 new tests: **274/274, twice consecutively, 0 skipped**, against the same
real Postgres + MinIO baseline.

## Requirement conformance

Status vocabulary per Part VIII: `CONFORMANT` / `NONCONFORMANT` /
`DEFERRED` / `NOT_APPLICABLE`. Evidence column cites the concrete
implementation and/or test; `real` marks tests that ran against actual
Postgres + MinIO, not fakes.

### Part II — Invariant 06 §6.8-6.11

| Req | Requirement | Status | Evidence |
|---|---|---|---|
| 6.8 | Deletion MUST be an explicit authorized lifecycle operation | CONFORMANT | `Permission.EVIDENCE_DELETE` (administrative-only), `request_deletion()`'s `authorized_by`/`validate_deletion_request()`; router-level `require_permission` (Phase 4) |
| 6.9 | Authorized deletion MUST produce the audit event required by Invariant 12 | CONFORMANT | `EVIDENCE_DELETION_REQUESTED` + `EVIDENCE_DELETED` (and `_RESULT_` equivalents), REQUIRED durability, dedupe-protected; `test_full_lifecycle_deletes_storage_and_db_and_audits_both_phases` (real) |
| 6.10 | Deletion MUST NOT be interpreted as historical content modification | CONFORMANT | Physical DELETE + separate tombstone table — no in-place mutation of the evidence row; structural (no `update()` on either repository) |
| 6.11 | Deleted sensitive content MUST NOT be retained merely because it appeared in audit metadata | CONFORMANT | Audit metadata for both `*_DELETION_REQUESTED`/`*_DELETED` events carries only `evidence_id`/`deletion_basis` — never `basis_reference`, content, object key, or checksum (explicit Phase-3 decision, tested: `test_request_deletion_audit_metadata_never_carries_basis_reference`) |

**Transition:** Part II's earlier (in-conversation) audit flagged §6.8-6.11
as the one NONCONFORMANT gap in Invariant 06, not covered by any deferred-
capability registry entry. All four are now CONFORMANT with real-
infrastructure evidence.

### Part III §3.26 — Evidence Deletion

| Req | Requirement | Status | Evidence |
|---|---|---|---|
| EVD-3.26.1 | MUST NOT be deleted through unrestricted arbitrary paths | CONFORMANT | Single path: `request_deletion()` -> `reconcile_deletion()`; no generic `delete()`/`update()` on either repository |
| EVD-3.26.2 | Deletion MUST identify authorization context | CONFORMANT | `authorized_by` required, validated (`validate_deletion_request`), server-derived from `principal.credential_id` at the router, never client-supplied |
| EVD-3.26.3 | Deletion MUST identify the applicable deletion basis | CONFORMANT | `DeletionBasis` closed vocabulary, required field, `OTHER_AUTHORIZED_BASIS` additionally requires a reference |
| EVD-3.26.4 | Deletion MUST produce an appropriate durable audit event | CONFORMANT | Same evidence as 6.9 |
| EVD-3.26.5 | Deletion MUST NOT retroactively alter an already-issued result | CONFORMANT (as of Phase 6 fix) | Prior to the Phase 6 fix this was at real risk of violation-by-crash (a stuck FK violation could leave a `EvidenceResult` referencing a half-deleted `Evidence`); the dependent-check now refuses the deletion outright rather than let it partially succeed, and superseded/original results are similarly protected |

### Part III §3.27 — Evidence Tombstones

| Req | Requirement | Status | Evidence |
|---|---|---|---|
| EVD-3.27.1 | A deleted evidence ID MUST remain distinguishable from an active evidence ID | CONFORMANT | `410 Gone` (tenant-owned) vs. `404` (cross-tenant/never-existed) — `test_deleted_evidence_returns_410_not_404`, `test_cross_tenant_deleted_evidence_is_ordinary_404_not_410` |
| EVD-3.27.2 | Tombstones MUST NOT contain deleted biometric or document content | CONFORMANT | Structural proof, not just documentation: `test_evidence_tombstone_has_no_field_capable_of_holding_raw_content` / `test_evidence_result_tombstone_has_no_result_field` assert the field set directly |
| EVD-3.27.3 | Tombstones MUST NOT represent deleted evidence as available | CONFORMANT | `list_evidence` excludes any tombstoned row (requested or executed) — Phase 4's `list_for_session` NOT EXISTS filter |
| EVD-3.27.4 | Tombstone retention MUST follow audit and privacy requirements | CONFORMANT (v1 scope) | Tombstones are never deleted by any v1 code path (no tombstone-delete capability exists at all); a distinct tombstone-retention *policy* beyond "retained indefinitely" is not implemented and not required for v1 — flagged as a natural extension point, not a gap, since indefinite retention of metadata-only records does not violate any active requirement |

### Part III §3.28 — Evidence Retention

| Req | Requirement | Status | Evidence |
|---|---|---|---|
| EVD-3.28.1 | Evidence MUST have an appropriate retention policy or classification | CONFORMANT | `retention_until` on `Evidence`/`EvidenceResult`, set at creation (`EvidenceService.add()`) |
| EVD-3.28.2 | Expired evidence MUST be eligible for authorized deletion | CONFORMANT | `list_expired(tenant_id, as_of)` on both repositories — real eligibility query, excludes already-tombstoned rows |
| EVD-3.28.3 | Retention policy MUST NOT silently override a legally required deletion process | NOT_APPLICABLE (v1) | No automatic enforcement exists at all (deliberately — see Deferred capability below), so there is no automated path that could silently override anything; the requirement has no v1 surface to violate |

### Part XI §11.29 — Data Deletion

| Req | Requirement | Status | Evidence |
|---|---|---|---|
| PRV-11.29.1 | Deletion MUST identify affected scope | CONFORMANT | Scope is exactly object storage + DB content per resource type, named explicitly in the reconciler's docstring and enforced by its own logic |
| PRV-11.29.2 | Deletion MUST require appropriate authorization | CONFORMANT | Same as EVD-3.26.2/6.8 |
| PRV-11.29.3 | Deletion MUST be auditable | CONFORMANT | Same as 6.9 |
| PRV-11.29.4 | Deletion MUST NOT silently leave active copies in governed stores | CONFORMANT (in-scope stores) | Both object storage and DB content are reconciled; backups/replicas are out of scope for v1 (no backup/replica infrastructure exists in this codebase to reconcile against) |
| PRV-11.29.5 | Impractical backup deletion MUST have backup-specific lifecycle semantics | NOT_APPLICABLE (v1) | No backup infrastructure exists yet |
| PRV-11.29.6 | Complete deletion MUST NOT be reported before scope is satisfied | CONFORMANT | `executed_at` set only after storage + DB + required audit all complete within one commit; proven adversarially by all 3 Phase-5 scenarios and the Phase-6 FK finding (which the system correctly refused to mark complete) |

### Part XI §11.30 — Deletion and Tombstones

| Req | Requirement | Status | Evidence |
|---|---|---|---|
| PRV-11.30.1 | Tombstones MUST NOT contain deleted raw biometrics or documents | CONFORMANT | Same as EVD-3.27.2 |
| PRV-11.30.2 | Tombstones MUST NOT contain deleted secrets | CONFORMANT | Tombstone schema has no field capable of holding a secret (structurally proven, same test) |
| PRV-11.30.3 | Tombstones MUST retain only accountability/lifecycle information | CONFORMANT | Exactly Part III §3.27's `EvidenceDeleted` fields, no more |
| PRV-11.30.4 | Auditability MUST NOT retain deleted content | CONFORMANT | Audit metadata excludes basis_reference/content (same as 6.11) |
| PRV-11.30.5 | Tombstone retention MUST have separate governance | CONFORMANT (v1 scope) | Same as EVD-3.27.4 |

### Part XI §11.35 — Erasure Interaction

| Req | Requirement | Status | Evidence |
|---|---|---|---|
| PRV-11.35.1 | Erasure MUST NOT automatically delete legally/operationally required audit records | CONFORMANT | Deletion never touches `audit_events`; the two lifecycle events *about* the deletion are themselves durable and outlive the deleted resource |
| PRV-11.35.2 | Retained accountability records MUST minimize personal content | CONFORMANT | Same as 11.30.3 |
| PRV-11.35.3 | Erasure MUST NOT fabricate historical states | CONFORMANT | `executed_at` semantics (11.29.6); the Phase-6 fix specifically prevents a fabricated partial-erasure state |
| PRV-11.35.4 | The relationship between erased evidence and retained provenance MUST be explicit | CONFORMANT | `evidence_integrity_reference` on the tombstone ties it back to the original `checksum`/`integrity_reference` |
| PRV-11.35.5 | Lawful deletion that prevents full reconstruction MUST preserve remaining provenance without recreating deleted content | CONFORMANT | Tombstone is the preserved provenance record; nothing recreates deleted content |

## Deferred capability: automatic retention sweep

Per Part IX §9.8 ("retention tooling... MAY be deferred only when their
absence does not violate the active contract") and the explicit,
pre-implementation decision: `list_expired(tenant_id, as_of)` exists at
the repository level on both domains (the operational capability), but no
scheduler, worker, or automatic purge exists or is triggered anywhere.
This is intentional and within the approved scope.

**Flagged, not fixed:** Part IX §9.3 (`DEF-9.3.1`-`DEF-9.3.4`) requires
every *formally* deferred capability to be recorded in a Deferred
Architecture Register with a unique capability ID, deferral reason,
activation preconditions, and periodic review status. **No such register
exists anywhere in this repository** — this predates Invariant-06 work
entirely and is a repository-wide gap affecting every other implicitly-
deferred capability (1:N search, advanced liveness, durable queues,
session resumption, etc.), not something introduced or expanded by this
remediation. Building the register is out of Phase 6's bounded scope
("do not implement new functionality"). Proposed entry for when the
register is created:

```
capability_id: DEF-EVD-RETENTION-SWEEP-001
name: Automatic retention-expiry deletion sweep
state: DEFERRED
reason: No concrete administrative workflow for retention-triggered
        deletion is designed yet; v1 exposes eligibility (list_expired)
        without automation, per user decision during Invariant-06
        discovery.
affected_components: core/evidence/, core/evidence_result/,
        infrastructure/deletion/
dependencies: none beyond what already exists (list_expired is live)
activation_preconditions: an administrative Management-API surface for
        retention-triggered deletion is designed and approved; a
        decision on scheduling mechanism (explicit non-goal: no
        Redis/Celery/worker without a separate architectural decision)
conformance_impact: none while deferred -- EVD-3.28.2/PRV-11.27.4 are
        satisfied by eligibility existing, not by automation existing
target_release: unscheduled
owner: unassigned
review_status: not yet reviewed
```

## Other gaps surfaced, not fixed (cross-cutting, out of this scope)

- **API-6.17.1 (`category` on every public error):** the app's shared
  `ErrorEnvelope`/`ErrorBody` schema has no `category` field anywhere.
  The new 410 response (Phase 4) has one because the approved response
  shape required it explicitly for that one endpoint — this does **not**
  make API-6.17.1 conformant generally. Fixing it properly touches
  essentially every exception handler in `main.py` and is tracked
  separately from Invariant-06.

## Verification summary

```
Requirement -> Implementation -> Verification Method -> Evidence -> Status
```

- Unit: `tests/unit/test_deletion_validation.py`, `test_deletion_models.py`,
  `test_evidence_deletion_service.py`, `test_evidence_result_deletion_service.py`
- Integration (real Postgres + MinIO): `tests/integration/test_evidence_deletion_service.py`,
  `tests/integration/test_evidence_deletion_failure_injection.py`
- Contract/HTTP (SQLite-backed `api_client`): `tests/contracts/security/test_evidence_deletion_api.py`
- Full repository suite: 274 passed / 0 skipped (real Postgres + MinIO baseline), run twice consecutively for repeatability

## Conclusion

Invariant-06 (Part II §6.8-6.11) is **CONFORMANT**. All directly-traced
requirements in Part III §3.26-3.28 and Part XI §11.29-11.30/11.35 are
CONFORMANT, DEFERRED (governed, registered above pending the register's
creation), or NOT_APPLICABLE to v1 scope, with real-infrastructure
evidence for every load-bearing claim. One genuine gap (FK dependents
with no `ON DELETE` behavior) was found during this closure review itself
— not by the phases that built the feature — fixed, and verified against
real Postgres both before and after. This closure record and the finding
within it are the argument for why Phase 6 existed as a real re-audit
rather than a formality: the gap would not have been caught by any test
written during Phases 1-5, because none of them happened to construct the
dependent-row shape that is the *normal* case once any evidence-processing
component exists.

Next: resume the paused Part II conformance pass, then proceed to the
Decision Engine track as planned.
