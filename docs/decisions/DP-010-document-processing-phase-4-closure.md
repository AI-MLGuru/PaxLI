# DP-010 — Document Processing Phase 4 Closure Record

**Status: CLOSED.** `DOCUMENT_FIELD_EXTRACTION` cross-source reconciliation
is implemented and hostile-validated. This record closes the phase; it
makes no new architectural decisions and reopens neither DP-008 nor
DP-009. The implementation validated both as written — a contract audit
against all 18 frozen invariants, performed directly against the code
(not inferred from tests alone), confirmed every one before hostile
validation began; HV-013 then found zero implementation defects on top
of that audit.

**Depends on:** `docs/decisions/DP-008-document-processing-phase-4-discovery.md`
(all decisions FROZEN/SELECTED), `docs/decisions/DP-001-document-processing-discovery.md`
Decision 7 as amended by Addendum A, `docs/decisions/DP-009-document-processing-phase-4-implementation-plan.md`
(FROZEN, all §7 items resolved).

---

## 1. Scope and governing decisions

Phase 4 added `DOCUMENT_FIELD_EXTRACTION` as a sixth `DocumentProcessor`
stage: a dedicated domain reconciler (`DocumentFieldReconciler`,
deliberately outside `core/document/capabilities.py`) consuming the
already-persisted effective `OCR_EXTRACTION`/`MRZ`/`BARCODE_QR` results
for the same capture, producing a canonicalized, conflict-aware result
via the eight canonical fields DP-001 Decision 7 froze. Governing
decisions carried in from DP-008/DP-009 and confirmed, not
re-litigated, by this closure:

- **DP-008 §5:** dedicated domain reconciler — not an image-processing
  capability (no `image: bytes` contract fits), not `DocumentProcessor`-
  internal logic (orchestration and domain reconciliation stay
  separate responsibilities).
- **DP-008 §3.5, DP-001 Addendum A:** `conflicted_fields: tuple[str, ...]`
  — the one minimal, narrowly-scoped amendment to Decision 7's frozen
  container, with a strict one-directional invariant (listed ⇒ null;
  null ⇏ listed).
- **DP-008 §3.9:** the reconciler may canonicalize equivalent
  representations; it may never select a source as authoritative. No
  source-authority rule exists anywhere in the implementation.
- **DP-008 §4:** derived-result freshness — reusable only while the
  effective parent set is unchanged, enforced via exact tuple identity
  on `parent_evidence_result_ids`, never content comparison.
- **DP-009 §7.1:** an MRZ row with `status=FAIL` (check-digit mismatch)
  is a usable reconciliation input, never `ABSENT` — its own `FAIL`
  status remains independently observable regardless.
- **DP-009 §7.3:** `extensions` is always `{}` in the deterministic
  baseline — only the eight canonical fields are reconciled.

## 2. Implementation commits

Unlike Phase 3's single feature commit, Phase 4 landed as six focused,
independently-auditable commits, each validated (mypy, ruff, full suite
×2) before the next began:

| Commit | Scope |
|---|---|
| `d30c99f` | §1 — schema/domain-type changes (`DocumentFieldExtractionResult`, `FieldReconciliationResult`) |
| `53f73ce` | §2/§3 — `FIELD_VALUE_CONFLICT` reason code, `DocumentFieldReconciler` contract |
| `ce38886` | §4 — `DeterministicFieldReconciler` (fixed source→canonical maps, one shared normalization function) |
| `e123866` | §6 — `EvidenceResultService.supersede()` lineage fix (required infrastructure gap, found while grounding §5) |
| `9e7cfd6` | §5 — `DocumentProcessor` integration (`_run_field_extraction`, translation helpers, DI wiring, full §9 test battery) |

`§6` landed before `§5` in commit order (not document order) because
`§5`'s freshness/recompute path genuinely depends on it — reflected
accurately in the commit chronology rather than forced into document
order.

## 3. HV-013 commit

`1c445af` — *test(document-processing): HV-013 hostile validation —
Phase 4 field reconciliation*, an immutable boundary separate from every
implementation commit (matching HV-011/HV-012's precedent). 2 files, 418
insertions, test-only. 15 new hostile tests, all passing on first run.

## 4. Validation evidence

| Check | Result |
|---|---|
| `mypy apps core infrastructure` | Clean, 167 source files, zero issues (re-confirmed after HV-013 and again at final regression) |
| `ruff check .` | Clean |
| `tests/unit/test_document_deterministic.py` (field-reconciler subset) | 23/23 (12 baseline + 11 HV-013) |
| `tests/unit/test_document_types.py` | 4/4 — `FieldReconciliationResult` invariant enforcement |
| `tests/unit/test_evidence_result_schemas.py` (field-extraction subset) | 2/2 |
| `tests/unit/test_evidence_result_service.py` (`supersede()` lineage subset) | 2/2 |
| `tests/integration/test_document_processor.py` | 42/42 (38 baseline + 4 HV-013) |
| Related integration suites (`test_verification_workflow.py`, `test_submit_api_wiring.py`, `test_evidence_result_persistence.py`) | 25/25 |
| Full suite, final regression, run 1 | 688/688 passed, 2m58s |
| Full suite, final regression, run 2 | 688/688 passed, 2m58s |
| `git diff --check` / `git status` at every commit boundary | Clean; exactly the expected files staged each time |

688 = 673 (through `9e7cfd6`) + 15 (HV-013). Both final-regression runs
were undisturbed, identical runtime — no repeat of the isolated ~20-minute
anomaly observed once during §1 validation (documented at the time as
environmental, never reproduced since, and irrelevant to Phase 4's own
code paths).

## 5. Contract audit — 18/18 confirmed

Before HV-013 began, every frozen DP-008/DP-009 invariant was checked
directly against the implementation's actual code (file:line citations,
not inferred from passing tests):

`DocumentFieldExtractionResult` matches Decision 7 + Addendum A exactly;
`FieldReconciliationResult.__post_init__` enforces both `conflicted_fields`
invariants (canonical-names-only, listed-implies-null); the deterministic
reconciler's `extensions={}` is a hardcoded literal; the reconciler
(`core/document/reconciliation.py`) imports no `EvidenceResult` type at
all and `_to_*_extraction` translation happens entirely in
`DocumentProcessor` before the call; `_to_mrz_extraction`'s signature has
no status parameter, structurally unable to special-case `FAIL`; the
reconciler treats all three sources uniformly with no authority
preference; normalization is one shared function applied identically
everywhere; freshness uses exact tuple identity, justified against the
repository's confirmed order-preserving storage; supersession (never
mutation) is the only write path; `parent_evidence_result_ids` threads
through both `create()` and `supersede()`; the status ternary has exactly
two branches (`PASS`/`INCONCLUSIVE`, no third); `FIELD_VALUE_CONFLICT` is
directly conditioned on `conflicted_fields`; the ambiguous-capture branch
returns before any row fetch or `reconcile()` call; every fetch/persist
is `tenant_id`-scoped; `classification.py` (untouched by Phase 4) still
maps `DOCUMENT_FIELD_EXTRACTION → HIGHLY_SENSITIVE`; and no `try/except`
wraps the `reconcile()` call in `_run_field_extraction`, so any exception
— including `CapabilityUnavailableError` itself — propagates uncaught.

## 6. Hostile-validation coverage (HV-013)

Attacked the reconciliation surface directly, per the frozen HV-013
matrix:

- **Unicode/normalization boundary:** Unicode case-folding (agreement),
  zero-width space (must NOT collapse — verified empirically against the
  real normalizer before asserting), embedded control characters (no
  crash, remain significant), genuinely different names (no false
  agreement), punctuation differences (no false agreement — the
  normalizer stays minimal, never becomes fuzzy matching).
- **Stored-representative invariant** (explicitly requested): three
  differently-formatted agreeing inputs (`"  John   Doe "`, `"john doe"`,
  `"JOHN DOE"`) produce the normalized value `"JOHN DOE"`; none of the
  three raw strings appears in the result.
- **MRZ FAIL as observation:** both directions — a FAIL-shaped
  `MRZExtraction` agreeing with another source, and disagreeing with
  one, proving `reconcile()`'s status-blind signature holds either way.
- **Conflict invariants:** three-way (not merely pairwise) disagreement
  still produces exactly one `conflicted_fields` entry; case-sensitive
  key matching (`"Full_Name"`) prevents near-miss canonical leakage.
- **Extensions boundary:** 20 unmapped keys plus deliberately
  near-miss-cased keys (`"FULL_NAME"`, `"Document_Number"`, a literal
  `"extensions"` key) across all three sources — `extensions` stays `{}`.
- **Never-reaches-FAIL:** four genuinely different conflict shapes
  (single-field, multi-field, mixed conflict-plus-agreement,
  all-absent) driven through the real pipeline — status never leaves
  `{PASS, INCONCLUSIVE}`.
- **Freshness/lineage, row identity vs. content:** a parent manually
  superseded with byte-identical result data still triggers recompute —
  proving freshness is keyed on which row, not what it contains.
- **Tenant isolation:** two tenants with real, *differing* data (not
  just an absent-data probe) — neither reconciliation ever reflects the
  other's.
- **Exception boundary:** a hostile double raising
  `CapabilityUnavailableError` itself — the one exception type every
  *other* stage's capability uses for expected failure — gets no special
  handling here either, since this stage has no `except` clause at all.

## 7. Findings / triage

**Zero implementation defects.** Two issues surfaced during test
authoring, both in the tests themselves, both caught and corrected
before being reported as results — recorded here as the discipline this
project expects, not omitted:

1. **§5's six-way partial-independence test** used an arbitrary barcode
   `document_number` that genuinely disagreed with MRZ's real
   ICAO-parsed value from the canonical reference vector — an unintended
   second conflict from the test author, not a reconciliation bug. Fixed
   by matching the fixture to MRZ's real value; corrected within the §5
   commit itself, not carried into HV-013.
2. **HV-013's row-identity freshness test** initially asserted raw
   ciphertext equality for byte-identical plaintext across two separate
   encryptions. AES-GCM's fresh-nonce-per-encryption is a correct
   security property, not a bug — identical plaintext legitimately
   produces different ciphertext. Fixed by decrypting and comparing
   plaintext, the correct layer for that assertion.

Neither reflects a defect in `core/document/reconciliation.py`,
`core/document/deterministic.py`, or `infrastructure/document/processor.py`.

## 8. Security / sensitivity confirmation

`DOCUMENT_FIELD_EXTRACTION` remains `HIGHLY_SENSITIVE`
(`core/evidence_result/classification.py:44`), unchanged and untouched by
any Phase 4 commit — confirmed both by the contract audit (§5 above) and
structurally by every round-trip test's encryption-boundary assertions
(`result_json is None`, `result_ciphertext is not None` for a populated
result). No cross-tenant data leaked in any HV-013 concurrency or
isolation test — confirmed by decrypting and comparing actual field
values, not inferred from row counts alone. `parent_evidence_result_ids`
lineage is validated through the same `_validate_provenance()` forgery
guard on both `create()` and `supersede()` (confirmed via a dedicated
unit test at the `§6` commit).

## 9. Explicit out-of-scope items (unchanged, not decided here)

- Real normalization/comparison library (date-semantic parsing, fuzzy
  name matching) — the deterministic baseline stays intentionally
  minimal, same discipline as every prior phase's deterministic
  stand-in.
- Document-type-specific field-mapping registry — a fixed per-source
  mapping is sufficient until a real adapter exists.
- Field-level provenance storage (`field_sources`) — DP-008 §3.4's
  conditional decision (reconstructibility via parent lineage +
  deterministic algorithm) stands as-is.
- `IdentityConsistency` / `DocumentAuthenticity` — DP-001's own distinct,
  still-untouched future items.
- Any Decision Engine change — `GateKind.CONFLICT` already existed and
  needed no modification; Phase 4's entire job was producing a
  policy-addressable signal for that existing mechanism to consume.

## 10. Final closure statement

Phase 4 (`DOCUMENT_FIELD_EXTRACTION` cross-source reconciliation) is
**CLOSED**. Six implementation commits (`d30c99f` through `9e7cfd6`) and
one immutable hostile-validation commit (`1c445af`) stand as the phase's
boundaries; none will be amended by this record. DP-008, DP-001 Addendum
A, and DP-009 are validated as written and are not reopened —
implementation and hostile validation together surfaced zero
architectural questions that discovery, reconciliation, or planning had
not already settled. The frozen contract has been implemented and
hostile-validated. **Further changes require a new decision/phase,
never a direct modification of the closed Phase 4 contract.** Working
tree is clean at closure.

## 11. Next phase boundary

The document-processing vertical slice (Phases 1-4) is now complete
against its own original scope. The next track is the **biometric/face
pipeline** — face capture, face quality, liveness, embedding, face
matching, reference-face acquisition, and external identity-provider
integration (NIMC/BVN territory, per DP-001's own deferred boundary).
Per this closure's own discipline, that work begins in **discovery
mode** — not implementation — mirroring DP-001/DP-003/DP-005/DP-008's
own process, not resumed until explicitly authorized. In particular, no
assumption about the shape of a NIMC/external-provider integration
(reference-template lookup vs. a biometric search/verification API)
should be carried in from this track — that question belongs to
biometric discovery itself, decided there, not inherited here.
