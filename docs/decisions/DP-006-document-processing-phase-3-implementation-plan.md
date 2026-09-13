# DP-006 — Document Processing Phase 3 Implementation Plan

**Status:** FROZEN — reconciliation complete. This document locks the Phase 3 implementation boundary from DP-005's twelve frozen decisions; it makes no new architectural decisions. One consistency issue was corrected during reconciliation: §3/§5's original wording could be read as Decision 3 ("`extract()` never returns `None`") overriding the pre-existing ambiguous-capture precondition that already short-circuits every stage before capability invocation — clarified that Decision 3 governs only what happens once `extract()` is actually called, not whether `_run_ocr` reaches that point for a given capture. Three further clarifications were folded in without changing any behavior: `_parse_ocr_fields()`'s deterministic contract made explicit, the unreadable-marker-wins precedence documented rather than left as an implicit accident of code order (with its own HV-012 test now named), and the marker-helper/capability-method responsibility boundary stated precisely. No production code has been changed at any point during discovery, reconciliation, or planning. **Implementation is now authorized against this plan.**
**Depends on:** `docs/decisions/DP-005-document-processing-phase-3-ocr-discovery.md` (all 12 decisions FROZEN), which itself depends on `docs/decisions/DP-001-document-processing-discovery.md` (7 frozen) and `docs/decisions/DP-003-document-processing-phase-2-discovery.md` (11 frozen).
**Scope:** deterministic, fully marker-driven `OCREngine`, producing real `OCR_EXTRACTION` `EvidenceResult` rows through the real `/submit` pipeline, extending `DocumentProcessor` without touching `_run_quality`/`_run_classification`/`_run_mrz`/`_run_barcode` or any WF/DE/HV-frozen contract. No `DOCUMENT_FIELD_EXTRACTION` work of any kind (schema or algorithm) — DP-005 Decision 0/11 defers both to Phase 4. No real OCR library/provider selection — that remains deferred to whichever future phase builds a real adapter.

---

## 1. Schema and domain-type changes

Two files, matching shape exactly (DP-005 Decision 7):

`core/evidence_result/schemas.py`:
```python
class OcrExtractionResult(BaseModel):
    raw: str
    fields: dict[str, str]
```

`core/document/types.py`:
```python
@dataclass(frozen=True)
class OCRExtraction:
    """Pure extracted data -- DP-005 Decision 7. Carries no outcome/status
    information of its own; see OCRReadOutcome/OCRReadResult below."""
    raw: str
    fields: dict[str, str]


class OCRReadOutcome(StrEnum):
    """Explicit domain-level pipeline outcome for one OCR attempt
    (DP-005 Decisions 1/2). Deliberately NOT EvidenceResultStatus --
    core/document/ MUST NOT import or produce EvidenceResultStatus
    directly (DP-001 Decision 3's domain/persistence boundary);
    DocumentProcessor alone translates this into an EvidenceResultStatus
    + reason code, via the explicit table in infrastructure/document/
    processor.py, never by inference."""
    UNREADABLE = "UNREADABLE"
    VALID = "VALID"
    # No FAIL/MALFORMED members -- DP-005 Decision 2. OCR has no
    # standards-defined negative condition and no structural grammar to
    # violate.


@dataclass(frozen=True)
class OCRReadResult:
    """Returned by OCREngine.extract() -- always, never None (DP-005
    Decision 3: OCR is applicable to every submitted classified document
    capture; there is no "nothing to process" case the way MRZ/Barcode
    have a zone/symbol that may genuinely be absent). `extraction` is
    None exactly when outcome=UNREADABLE."""
    outcome: OCRReadOutcome
    extraction: OCRExtraction | None
```

`core/evidence_result/classification.py` — no change. `OCR_EXTRACTION` is already `HIGHLY_SENSITIVE` since Phase 0/DP-001 Decision 1; DP-005 Decision 10 confirmed no reassessment is warranted.

**`fields: dict[str, str]` is a Phase 3 source-specific extraction representation, not a canonical identity/document schema** — restating DP-001 Decision 7 and DP-005's own repeated framing, not deciding anything new. The canonical cross-source representation remains `DOCUMENT_FIELD_EXTRACTION`'s already-frozen (but still unimplemented) hybrid schema, entirely out of scope here per DP-005 Decision 0.

---

## 2. Reason codes

`core/document/reason_codes.py`, extending `DocumentReasonCode` (DP-005 Decision 5):
```python
class DocumentReasonCode(StrEnum):
    DOCUMENT_UNSUPPORTED = "DOCUMENT_UNSUPPORTED"
    IMAGE_TOO_BLURRY = "IMAGE_TOO_BLURRY"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    AMBIGUOUS_DOCUMENT_CAPTURE = "AMBIGUOUS_DOCUMENT_CAPTURE"
    MRZ_UNREADABLE = "MRZ_UNREADABLE"
    MRZ_MALFORMED = "MRZ_MALFORMED"
    MRZ_CHECK_DIGIT_MISMATCH = "MRZ_CHECK_DIGIT_MISMATCH"
    BARCODE_UNREADABLE = "BARCODE_UNREADABLE"
    BARCODE_PAYLOAD_UNRECOGNIZED = "BARCODE_PAYLOAD_UNRECOGNIZED"
    BARCODE_PAYLOAD_MALFORMED = "BARCODE_PAYLOAD_MALFORMED"
    OCR_UNREADABLE = "OCR_UNREADABLE"                              # NEW
```
One new member — `OCR_UNREADABLE`, spec-blessed (EVD-3.14), not a PaxLI coinage the way every MRZ/Barcode code was. `MODEL_UNAVAILABLE`/`AMBIGUOUS_DOCUMENT_CAPTURE` reused unchanged. No other OCR-specific code is added, per DP-005 Decision 5's explicit discipline against coining codes the two-outcome vocabulary gives no operational use for yet.

---

## 3. Capability contract

`core/document/capabilities.py`:
```python
class OCREngine(ABC):
    """DP-005 Phase 3."""

    @abstractmethod
    async def extract(self, image: bytes) -> OCRReadResult:
        """Always returns a populated OCRReadResult -- never None (DP-005
        Decision 3). OCR has no capability-level absence/not-applicable
        state: whenever this method is actually called, inability to
        recognize usable text is the outcome UNREADABLE, never an
        absence of applicability. This says nothing about WHETHER the
        capability gets called for a given capture -- DocumentProcessor's
        existing ambiguous-capture precondition (§5) still short-circuits
        BEFORE any capability invocation, exactly as it already does for
        every other stage; that is pipeline-level precondition handling,
        not a capability-level absence state, and Decision 3 does not
        touch it."""
        raise NotImplementedError
```

This is the one place Phase 3's contract structurally differs from Phase 2's `MRZParser`/`BarcodeDecoder` pattern (both `Optional`-returning) — a deliberate, DP-005-frozen departure, not an oversight or a partial application of the Phase 2 template. **Precisely scoped:** Decision 3 establishes that `extract()`, once invoked, never returns `None` — it says nothing about the pipeline-level question of whether `_run_ocr` reaches the point of invoking it at all for a given capture. The ambiguous-capture precondition (§5) is unchanged, pre-existing pipeline machinery shared by all five stages, not a second, competing absence concept for OCR specifically.

---

## 4. `DeterministicOCREngine` implementation

`core/document/deterministic.py`, extending the existing module:

```python
_OCR_UNREADABLE_MARKER = b"PAXLI_TEST_OCR_UNREADABLE"
_OCR_VALID_PREFIX = b"PAXLI_TEST_OCR_VALID:"
_OCR_PAYLOAD_MAX_BYTES = 2048
_OCR_MARKER_TERMINATOR = b"\x00"


def _extract_ocr_test_marker(image: bytes) -> str | None:
    """Returns None (no OCR marker at all), "" (the explicit unreadable
    marker, or a found marker whose payload can't be decoded as text),
    or the raw recognized text following a found-OCR marker. Matches
    only the exact literal prefixes above -- never a fuzzy/partial
    match, never an interpretation of arbitrary document content. This
    function returns no usable marker text for anything outside its
    recognized deterministic fixture format; it is DeterministicOCREngine.
    extract() below, not this helper, that converts that condition into
    the actual OCRReadOutcome.UNREADABLE domain value -- this function
    only ever returns plain str | None, never an OCRReadResult itself.

    Marker precedence: if both the explicit unreadable marker and a
    valid-marker prefix are present in the same image, the unreadable
    marker wins (checked first, unconditionally). This is fixture
    behavior only, arbitrarily chosen for deterministic-test purposes --
    it has no bearing on how a future real OCR adapter would behave, and
    is deliberately exercised by a dedicated HV-012 test (§8) rather than
    left as an untested accident of code order."""
    if _OCR_UNREADABLE_MARKER in image:
        return ""
    index = image.find(_OCR_VALID_PREFIX)
    if index == -1:
        return None
    start = index + len(_OCR_VALID_PREFIX)
    end = image.find(_OCR_MARKER_TERMINATOR, start, start + _OCR_PAYLOAD_MAX_BYTES)
    raw_bytes = image[start:end] if end != -1 else image[start : start + _OCR_PAYLOAD_MAX_BYTES]
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _parse_ocr_fields(raw: str) -> dict[str, str]:
    """Deterministic test-fixture parser only -- NOT a field-extraction
    or reconciliation algorithm, and must never grow into one. Contract:
    split `raw` on `;`; split each resulting segment on the FIRST `=`;
    a segment with no `=` is silently ignored (not an error); no
    normalization, casing, whitespace-trimming, or canonical-field
    interpretation of any kind is applied -- `fields` stays exactly as
    informal/non-canonical as Decision 7/§1 requires. Identical in
    spirit to Barcode's `_parse_kv_payload()` (Phase 2)."""
    fields: dict[str, str] = {}
    for segment in raw.split(";"):
        key, separator, value = segment.partition("=")
        if separator and key:
            fields[key] = value
    return fields


class DeterministicOCREngine(OCREngine):
    """Fully stand-in -- no real recognition logic (DP-005 Decision 8),
    mirroring DeterministicBarcodeDecoder's pattern exactly. Real OCR is
    deferred to a future real-adapter phase."""

    async def extract(self, image: bytes) -> OCRReadResult:
        marker_text = _extract_ocr_test_marker(image)
        if not marker_text:  # covers both None (no marker) and "" (explicit unreadable)
            return OCRReadResult(outcome=OCRReadOutcome.UNREADABLE, extraction=None)
        return OCRReadResult(
            outcome=OCRReadOutcome.VALID,
            extraction=OCRExtraction(raw=marker_text, fields=_parse_ocr_fields(marker_text)),
        )
```

**Narrow implementation choice, flagged explicitly (not a new architectural decision — this is exactly the class of thing DP-002/DP-004 called out the same way):** `if not marker_text:` collapses `_extract_ocr_test_marker`'s two "nothing usable" returns (`None` = no marker present at all, `""` = explicit unreadable marker or undecodable payload) into the single `UNREADABLE` outcome, since DP-005 Decision 3 already forecloses any `NOT_SUBMITTED`-shaped distinction between them — there is no third outcome for a missing-marker case to map to. This is the direct, structural consequence of Decision 3, not a separate choice being made here. This conversion happens entirely inside `DeterministicOCREngine.extract()` — `_extract_ocr_test_marker()` itself never touches `OCRReadOutcome`/`OCRReadResult` at all, keeping the marker-scanning helper and the outcome-producing capability method cleanly separated.

**Marker-mechanism safety boundary — restating DP-004's established rule, not inventing a new one:** `_extract_ocr_test_marker()` matches only its exact literal prefix, never interprets arbitrary document content as an instruction, and returns no usable marker text for anything outside its recognized deterministic fixture format — including genuinely non-UTF-8 bytes following the prefix, which `DeterministicOCREngine.extract()` then converts to `UNREADABLE`, never an exception. It is private implementation scaffolding, not part of `OCREngine`'s externally observable contract; a future real adapter has no obligation to recognize this marker format, including its precedence rule above. Runs against real, attacker-controlled document bytes in production exactly like every other deterministic capability, per Phase 1/2's established DI wiring (§6).

**`utf-8`, not `ascii`, decoding — a deliberate, narrow departure from MRZ/Barcode's marker decoding, flagged explicitly.** MRZ's ICAO 9303 alphabet and Barcode's test schema are both ASCII-only by construction; OCR's recognized text is, by DP-005 §6 point 3's own finding, the one capability whose output is genuinely unconstrained Unicode (SEC-7.21's "unexpected Unicode" category applies to OCR specifically). Decoding as `utf-8` (falling back to `UNREADABLE` on failure, exactly like the `ascii` paths do for MRZ/Barcode) lets the deterministic stand-in actually carry adversarial Unicode payloads through the full pipeline for HV-012 to attack, rather than artificially restricting the test surface to ASCII the way the other two capabilities' real formats already do.

---

## 5. `DocumentProcessor` extension

`infrastructure/document/processor.py`. One new stage, added to `process()`'s existing sequential list, after barcode:

```python
await self._run_quality(...)          # unchanged
await self._run_classification(...)   # unchanged
await self._run_mrz(...)              # unchanged, Phase 2
await self._run_barcode(...)          # unchanged, Phase 2
await self._run_ocr(...)              # NEW
```

Outcome map (DP-005 §7's frozen table, encoded directly):
```python
_OCR_OUTCOME_MAP: dict[OCRReadOutcome, tuple[EvidenceResultStatus, str | None]] = {
    OCRReadOutcome.UNREADABLE: (EvidenceResultStatus.INCONCLUSIVE, DocumentReasonCode.OCR_UNREADABLE.value),
    OCRReadOutcome.VALID: (EvidenceResultStatus.PASS, None),
}
# Exhaustiveness test: every OCRReadOutcome member has an entry here.
```

`_run_ocr` follows the exact shape `_run_mrz`/`_run_barcode` already established, with one simplification that falls directly out of DP-005 Decision 3 — there is no `if read_result is None: ... NOT_SUBMITTED` branch, because `extract()` never returns `None`:

```python
async def _run_ocr(
    self, *, session_id, tenant_id, capture_id, object_key, ambiguous, request_id, correlation_id,
) -> None:
    async with self._session_factory() as session:
        service = self._build_evidence_result_service(session)
        existing = await service.get_effective_for_session_by_type(
            session_id=session_id, tenant_id=tenant_id, evidence_type=EvidenceResultType.OCR_EXTRACTION,
        )
        if existing is not None and _is_reusable(existing.status):
            return

        if ambiguous:
            await self._persist_stage(
                service, existing, session_id=session_id, tenant_id=tenant_id,
                evidence_type=EvidenceResultType.OCR_EXTRACTION, status=EvidenceResultStatus.INCONCLUSIVE,
                reason_codes=(DocumentReasonCode.AMBIGUOUS_DOCUMENT_CAPTURE.value,),
                producer=_PRODUCER_OCR, request_id=request_id, correlation_id=correlation_id,
            )
            await session.commit()
            return

        assert object_key is not None and capture_id is not None  # ambiguous handled above
        image = await self._storage.get(object_key)
        try:
            read_result = await self._ocr_engine.extract(image)
        except CapabilityUnavailableError as exc:
            await self._persist_stage(
                service, existing, session_id=session_id, tenant_id=tenant_id,
                evidence_type=EvidenceResultType.OCR_EXTRACTION, status=EvidenceResultStatus.UNAVAILABLE,
                reason_codes=(exc.reason_code,), producer=_PRODUCER_OCR, source_reference=capture_id,
                request_id=request_id, correlation_id=correlation_id,
            )
            await session.commit()
            return

        status, reason_code = _OCR_OUTCOME_MAP[read_result.outcome]
        result_payload = (
            {"raw": read_result.extraction.raw, "fields": read_result.extraction.fields}
            if read_result.extraction is not None else None
        )
        await self._persist_stage(
            service, existing, session_id=session_id, tenant_id=tenant_id,
            evidence_type=EvidenceResultType.OCR_EXTRACTION, status=status,
            reason_codes=(reason_code,) if reason_code else (),
            result=result_payload, producer=_PRODUCER_OCR, source_reference=capture_id,
            request_id=request_id, correlation_id=correlation_id,
        )
        await session.commit()
```

**`EvidenceResult.result=None` semantics — restating DP-004's already-established behavior, not a new rule.** When `outcome=UNREADABLE`, `read_result.extraction is None`, so `result_payload` is `None` and a real `EvidenceResult` row is still persisted with `status=INCONCLUSIVE`, `result=None` — the stage's outcome and reason code fully represent what happened; an absent payload is informative in its own right, exactly as DP-004 §6 established for MRZ/Barcode's `UNREADABLE` states.

**Producer constant:**
```python
_PRODUCER_OCR = "document-ocr-engine-deterministic"
```
`_PRODUCER_VERSION = "1.0"` reused unchanged.

**Constructor** gains one new required parameter:
```python
class SqlAlchemyDocumentProcessor:
    def __init__(
        self,
        session_factory, key_provider, key_id, storage,
        quality_assessor: QualityAssessor,
        document_classifier: DocumentClassifier,
        mrz_parser: MRZParser,
        barcode_decoder: BarcodeDecoder,
        ocr_engine: OCREngine,           # NEW
    ) -> None: ...
```

---

## 6. Workflow / DI wiring

`apps/api/paxli_api/dependencies.py`'s `get_workflow_service()` gains the corresponding construction: `DeterministicOCREngine()` passed alongside the existing four deterministic capabilities. `core/verification/workflow.py` is untouched — `document_processor.process()` is already called unconditionally from the `PROCESSING` branch; the new stage rides inside `process()`'s own internal sequence.

Every existing test that constructs `SqlAlchemyDocumentProcessor` directly or calls `get_workflow_service()` directly (`tests/integration/test_document_processor.py`, `test_submit_api_wiring.py`, `test_verification_workflow.py`) needs its construction call updated with the one new required argument — the same class of mechanical breakage DP-002's and DP-004's rollouts both went through, expected, not a surprise regression when it happens.

---

## 7. Testing strategy

- **`tests/unit/`**: `DeterministicOCREngine`'s two outcome branches (no-marker → `UNREADABLE`, explicit-unreadable-marker → `UNREADABLE`, valid-marker → `VALID`), confirming the collapse described in §4 is deliberate and tested, not accidental; the marker-safety-boundary tests mirroring DP-004/HV-011's pattern (incidental substrings never interpreted, non-UTF-8 payload degrades safely, marker found amid surrounding noise); `_OCR_OUTCOME_MAP` exhaustiveness.
- **`tests/integration/`** (real Postgres + MinIO): full round-trip for both outcome states plus `UNAVAILABLE`, correct `source_reference` lineage; retry-convergence both directions (an `UNAVAILABLE` OCR result superseded by a real attempt; a call-count assertion proving `VALID`/`UNREADABLE` are not recomputed on a second `process()` call, mirroring DP-004/HV-011's two-sided proof); the ambiguity test extended to the fifth stage; partial-stage independence (OCR `UNREADABLE` while MRZ/Barcode/Quality/Classification all succeed, and the reverse); a full `/submit`-driven policy test proving a policy can require and condition on `OCR_EXTRACTION` today through the unmodified Decision Engine, mirroring DP-004's MRZ-specific proof exactly.
- **`tests/unit/` — HIGHLY_SENSITIVE confirmation**: `OCR_EXTRACTION` is already covered by the existing parametrized encryption-at-rest test (`tests/integration/test_evidence_result_persistence.py`, added during HV-010) — confirm it still passes with the new `raw` field included in the payload shape, extending the parametrized case rather than adding a new test.

---

## 8. HV-012 attack surface (preview only — not run from this document)

Once Phase 3 lands: adversarial OCR-output text specifically (SEC-7.21's "unexpected Unicode" category, directly cited in DP-005 §6 point 3 as OCR's own distinguishing risk — right-to-left scripts, combining characters, zero-width characters, homoglyphs, control characters, all carried through the `utf-8`-decoding marker mechanism §4 deliberately enables); marker-boundary hostile inputs mirroring HV-011's pattern (incidental substrings, truncation, non-decodable payloads), including a dedicated test with both the unreadable and valid markers present in the same image, confirming the documented precedence (§4 — unreadable wins) holds and is not an untested accident of code order; concurrency at the new call site specifically plus cross-capture non-interference, not assumed inherited from HV-011's generic proof; exception injection for `OCREngine` specifically; tenant isolation extended to all five `DocumentProcessor` stages; full five-way partial-stage independence; direct confirmation that `OCR_EXTRACTION` never reaches `FAIL` under any tested input, mirroring HV-011's `BARCODE_QR`-never-`FAIL` proof.

---

## 9. Dependency policy

**No new runtime dependency is added in Phase 3.** `DeterministicOCREngine` is entirely fixture-marker-driven, requiring no OCR library, no ML/vision dependency, no native codec. `pyproject.toml` is untouched. Consistent with every prior phase's "library selection deferred" pattern (DP-001 §12, DP-003 §1, DP-004 §10) — real OCR library/provider selection remains a future, dedicated decision, not made here.

---

## 10. Explicit non-goals for Phase 3

- No real (non-deterministic) OCR recognition — fully fixture-marker stand-in per §4.
- No `DOCUMENT_FIELD_EXTRACTION` schema implementation or reconciliation algorithm of any kind (DP-005 Decision 0/11) — not even the schema alone; both are deferred together to Phase 4.
- No `IDENTITY_CONSISTENCY` work (DP-001 Open Question 5, still untouched).
- No `AuthenticityChecker`/`DOCUMENT_AUTHENTICITY` (DP-001 Decision 6, unchanged).
- No confidence/quality scoring on `OcrExtractionResult` (DP-005 Decision 6).
- No new reason codes beyond `OCR_UNREADABLE` (DP-005 Decision 5).
- No `DocumentType`-based branching around whether `_run_ocr` executes (DP-005 Decision 3) — unconditional invocation, matching every other stage.
- No `CircuitBreaker`/`RetryPolicy`/timeout wrapper around the new capability call — same reasoning as every prior phase: a deterministic, in-process, pure function has nothing genuine to circuit-break against yet.
- No changes to `VerificationWorkflowService`, `DecisionOrchestrator`, `core/policy/`, or any WF/DE/HV-frozen contract.
- No new runtime dependency (§9).

---

## 11. Closure criteria

Phase 3 is done when: `DocumentProcessor` produces real, correctly-lineaged `OCR_EXTRACTION` `EvidenceResult` rows across every outcome state in DP-005 §7's frozen table, `OCR_EXTRACTION` is confirmed by direct test to never emit `FAIL`, a policy can require and condition on `OCR_EXTRACTION` today through the unmodified Decision Engine, retried `/submit` calls converge without re-invoking already-satisfied stages, the full test suite passes twice consecutively, mypy/ruff are clean, and a scoped HV-012 pass against exactly this new surface (§8) comes back clean or with findings triaged the same way every HV-00X finding has been this session — fixed, disclosed, or explicitly deferred, never silently ignored.

If implementation exposes something DP-005 didn't actually decide — not merely an implementation-level narrow choice of the kind §4 flags explicitly, but a genuine architectural gap — work stops and the appropriate discovery decision gets made explicitly, not silently resolved in code.
