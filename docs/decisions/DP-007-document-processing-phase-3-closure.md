# DP-007 — Document Processing Phase 3 Closure Record

**Status: CLOSED.** Phase 3 (OCR) is implemented, hostile-validated, and
fully committed. This record closes the phase; it makes no new
architectural decisions and reopens neither DP-005 nor DP-006. The
implementation validated both plans as written — no architectural
surprise surfaced during implementation or hostile validation that
required returning to discovery or reconciliation.

**Depends on:** `docs/decisions/DP-005-document-processing-phase-3-ocr-discovery.md`
(12 decisions FROZEN) and `docs/decisions/DP-006-document-processing-phase-3-implementation-plan.md`
(FROZEN), which themselves depend on `docs/decisions/DP-001-document-processing-discovery.md`
(7 frozen) and `docs/decisions/DP-003-document-processing-phase-2-discovery.md`
(11 frozen).

---

## 1. Scope and governing decisions

Phase 3 added a deterministic, fully marker-driven `OCREngine` capability
producing real `OCR_EXTRACTION` `EvidenceResult` rows through the real
`/submit` pipeline, extending `DocumentProcessor` without touching
`_run_quality`/`_run_classification`/`_run_mrz`/`_run_barcode` or any
prior WF/DE/HV-frozen contract. Governing decisions carried in from
DP-005/DP-006 and confirmed, not re-litigated, by this closure:

- **DP-005 Decision 0/11:** `DOCUMENT_FIELD_EXTRACTION` reconciliation is
  explicitly out of scope, deferred whole to Phase 4.
- **DP-005 Decision 2:** OCR has no standards-defined negative condition
  — `OCRReadOutcome` has exactly two members (`UNREADABLE`, `VALID`), no
  `FAIL`.
- **DP-005 Decision 3:** `OCREngine.extract()` is non-optional — OCR has
  no capability-level absence/not-applicable state. The pre-existing
  ambiguous-capture short-circuit in the processor pipeline still governs
  *whether* the stage is reached; Decision 3 governs only what happens
  once it is.
- **DP-005 Decision 7:** `raw: str` + `fields: dict[str, str]` schema,
  matching shape between `core/document/types.py` and
  `core/evidence_result/schemas.py`.
- **DP-005 Decision 9:** terminal/reusable convergence — a persisted OCR
  result (either outcome) is not recomputed on retry.
- **Added governing principle (DP-005):** a capability's `VALID` asserts
  only that it satisfied its own output contract — never correctness,
  authenticity, or identity validity.

## 2. Implementation commit

`0f435ea` — *feat(document-processing): implement Phase 3 OCR processing*.
13 files, 810 insertions / 40 deletions: `OCRReadOutcome`/`OCRReadResult`
domain types, `OCR_UNREADABLE` reason code, the non-optional `OCREngine`
capability contract, `DeterministicOCREngine`, `DocumentProcessor._run_ocr`
/ `_OCR_OUTCOME_MAP` ([infrastructure/document/processor.py:99](../../infrastructure/document/processor.py#L99)),
DI wiring, and the DP-006 §7-mandated integration/unit test suite
(tenant isolation, retry/reuse convergence, full round-trip with
encryption-boundary checks, 5-way partial-stage independence, exception
taxonomy, policy visibility, concurrency at OCR's own call site).

## 3. HV-012 commit

`9aa305e` — *test(document-processing): HV-012 hostile validation — Phase
3 OCR*, an immutable boundary separate from the implementation commit
(matching HV-011's precedent for Phase 2). 2 files, 369 insertions, test-only.
12 new hostile tests, all passing on first run.

## 4. Validation evidence

| Check | Result |
|---|---|
| `mypy apps core infrastructure` | Clean, 166 source files, zero issues (both after `0f435ea` and after `9aa305e`) |
| `ruff check .` | Clean |
| `tests/integration/test_document_processor.py` | 32/32 passed |
| `tests/unit/test_document_deterministic.py` | 42/42 passed (OCR subset: 19) |
| `tests/unit/test_document_processor_outcome_maps.py` | Exhaustiveness + no-FAIL confirmed: [test_ocr_outcome_map_is_exhaustive:65](../../tests/unit/test_document_processor_outcome_maps.py#L65), [test_no_ocr_outcome_ever_maps_to_fail:75](../../tests/unit/test_document_processor_outcome_maps.py#L75) |
| Related integration suites (`test_verification_workflow.py`, `test_submit_api_wiring.py`, `test_evidence_result_persistence.py`) | 25/25 passed |
| Full suite, post-`0f435ea`, run 1 | 635/635 passed |
| Full suite, post-`0f435ea`, run 2 | 634/635 passed — see §7 |
| Full suite, post-`9aa305e`, run 1 | 647/647 passed |
| Full suite, post-`9aa305e`, run 2 | 647/647 passed |
| `git status` / `git diff --check` at both commit boundaries | Clean; exactly the expected files staged each time |

647 = 635 + 12 (the HV-012 hostile tests). Both post-HV-012 runs were
undisturbed — the environmental timeout in §7 did not recur.

## 5. Hostile-validation coverage (HV-012)

Attacked the OCR surface directly, per the frozen attack matrix:

- **Unicode hostility:** mid-multibyte-character truncation at the
  2048-byte window boundary ([test_ocr_engine_payload_truncated_mid_multibyte_character_degrades_to_unreadable_not_a_crash:423](../../tests/unit/test_document_deterministic.py#L423)),
  C0 control characters surviving raw payload
  ([:443](../../tests/unit/test_document_deterministic.py#L443)),
  homoglyph prefix spoofing ruled out by exact-literal matching
  ([:458](../../tests/unit/test_document_deterministic.py#L458)), long
  mixed Unicode/ASCII round-trip. (RTL script, combining characters, and
  zero-width characters were already covered in the implementation
  commit's own adversarial-Unicode test.)
- **Marker-boundary attacks:** truncated valid prefix, empty payload
  between prefix and terminator, terminator at the last valid window
  byte ([:497](../../tests/unit/test_document_deterministic.py#L497)),
  terminator exactly one byte past the window
  ([:518](../../tests/unit/test_document_deterministic.py#L518)) —
  both boundary directions confirmed by direct probe against
  `_extract_ocr_test_marker` before asserting, not guessed. (Incidental
  substrings, both-markers-present precedence, invalid UTF-8, and noise-
  surrounded markers were already covered in the implementation commit.)
- **Pipeline isolation:** OCR UNREADABLE alongside MRZ/Barcode/Quality/
  Classification all PASS ([test_ocr_unreadable_does_not_affect_other_stages:1355](../../tests/integration/test_document_processor.py#L1355)),
  and the explicit no-implicit-reconciliation proof — a VALID OCR result
  never manufactures a `DOCUMENT_FIELD_EXTRACTION` row
  ([test_ocr_processing_never_writes_document_field_extraction:1401](../../tests/integration/test_document_processor.py#L1401)).
- **Concurrency:** cross-tenant race — a real owner's `process()` call
  concurrent with an attacker's forged-tenant call for the same
  `session_id` ([test_concurrent_cross_tenant_processing_does_not_leak_or_corrupt:527](../../tests/integration/test_document_processor.py#L527)),
  and OCR-specific cross-capture non-interference with the *decrypted*
  raw text verified (not just row/status separation) to rule out the
  marker-extraction helpers mixing up which image produced which text
  under a race ([test_concurrent_ocr_processing_of_different_captures_does_not_interfere:824](../../tests/integration/test_document_processor.py#L824)).
- **Tenant isolation, exception taxonomy, outcome integrity, persistence/
  security, policy boundary:** already exercised directly in the
  implementation commit's own test suite (DP-006 §7 mandated this
  coverage as part of implementation, not deferred to HV-012) —
  confirmed present and re-run clean here rather than re-derived.

## 6. Findings / triage

**None.** All 12 HV-012 tests passed on first run. No implementation
defect was found, patched, or requires disclosure. This mirrors HV-011's
result for Phase 2.

## 7. Environmental observation — rate-limit timeout

During post-`0f435ea` validation (before HV-012 began), the second of two
consecutive full-suite runs produced one failure:
`tests/integration/test_rate_limit_persistence.py::test_concurrent_contention_admits_at_most_the_limit`,
a `RateLimiterUnavailableError` from a 2-second Postgres dependency
timeout. This is unrelated to any Phase 3/OCR code path. Reproduced
independently (failed again in isolation, with individual check
durations climbing to ~4.7s) and attributed to genuine host/Docker
contention at that moment — confirmed directly by timing a bare
`docker exec averiq-postgres-1 pg_isready`, which itself took 2.35s, far
outside its normal near-instant response. This is exactly the noise
pattern that test's own docstring documents and instructs how to rule
out. Recorded here rather than overstated as a clean run; both
post-`9aa305e` full-suite runs were subsequently undisturbed by it.

## 8. Security / sensitivity confirmation

`OCR_EXTRACTION` remains `HIGHLY_SENSITIVE`
([core/evidence_result/classification.py:43](../../core/evidence_result/classification.py#L43)),
unchanged from Phase 0/DP-001 Decision 1; DP-005 Decision 10 confirmed no
reassessment was warranted, and this closure re-confirms it structurally
via the full round-trip test's encryption-boundary assertions
([test_ocr_full_round_trip_covers_every_outcome_state:1258](../../tests/integration/test_document_processor.py#L1258):
`result_json is None`, `result_ciphertext is not None` for a populated
result). No raw OCR text, tenant identifier, or capture identifier
leaked across the tenant or capture boundary in any HV-012 concurrency
test — confirmed by decrypting and comparing actual payload content, not
inferring from row counts alone.

## 9. Explicit out-of-scope items (unchanged, not decided here)

- `DOCUMENT_FIELD_EXTRACTION` schema and cross-source reconciliation
  algorithm — DP-005 Decision 0/11, deferred whole to Phase 4.
- A real OCR provider/model adapter — `DeterministicOCREngine` remains a
  full marker-driven stand-in; provider selection is deferred to
  whichever future phase builds a real adapter.
- `parent_evidence_result_ids` — still has zero real callers anywhere in
  the codebase; reserved for the still-unbuilt reconciliation stage.
- DP-001 Open Question 3 (ultimate home for reason-code taxonomies) —
  still open, untouched by Phase 3.

## 10. Final closure statement

Phase 3 (OCR) is **CLOSED**. `0f435ea` (implementation) and `9aa305e`
(HV-012) stand as the phase's two immutable commit boundaries; neither
will be amended by this record. DP-005 and DP-006 are validated as
written and are not reopened — implementation surfaced zero architectural
questions that discovery or reconciliation had not already settled.
Working tree is clean at closure.

## 11. Next phase boundary

The next document-processing capability is **Phase 4:
`DOCUMENT_FIELD_EXTRACTION` + cross-source reconciliation** — the
question DP-003 Decision 11 and DP-005 Decision 0/11 both deliberately
deferred, anchored by EVD-3.25 (Evidence Conflicts), DEC-5.22 (Conflict
Resolution), and Invariant-02 §2.5. Per this closure's own discipline,
Phase 4 begins in **discovery mode** — not implementation — mirroring
DP-001/DP-003/DP-005's own process, not resumed until explicitly
authorized.
