# DP-004 — Document Processing Phase 2 Implementation Plan

**Status:** FROZEN — reconciliation complete. This document locks the Phase 2 implementation boundary from DP-003's eleven frozen decisions; it makes no new architectural decisions. §3's outcome-wrapper design (`MRZReadOutcome`/`BarcodeReadOutcome`/`MRZReadResult`/`BarcodeReadResult`) was substantially revised during reconciliation, replacing an initially-proposed sentinel-value approach that was correctly rejected as fragile. Four further clarifications were reconciled in afterward — none reopening DP-001/DP-002/DP-003: an `Optional`-return capability contract principle (§3), `EvidenceResult.result=None` semantics made explicit (§6), `dict[str, str]` explicitly bounded as phase-local, non-canonical (§1), and a marker-mechanism safety boundary (§5, one genuinely new requirement plus restated Phase 1 precedent). A subsequent self-check against DP-001–003 also closed two test-coverage gaps in §8 (a full pipeline-through-policy test; two-sided retry-convergence coverage) and wrote out `_BARCODE_OUTCOME_MAP` explicitly rather than by shorthand. No production code has been changed at any point during discovery, reconciliation, or planning. **Implementation is now authorized against this plan.**
**Depends on:** `docs/decisions/DP-003-document-processing-phase-2-discovery.md` (all 11 decisions FROZEN), which itself depends on `docs/decisions/DP-001-document-processing-discovery.md` (all 7 decisions FROZEN).
**Scope:** deterministic `MRZParser` (real ICAO 9303 check-digit validation, stand-in zone-detection) + fully stand-in `BarcodeDecoder`, producing real `MRZ`/`BARCODE_QR` `EvidenceResult` rows through the real `/submit` pipeline, extending `DocumentProcessor` without touching `_run_quality`/`_run_classification` or any WF/DE/HV-frozen contract.

---

## 1. Schema and domain-type changes

Two changes total, both DP-003 Decision 6's `symbology` field — nothing else moves.

`core/evidence_result/schemas.py`:
```python
class MrzResult(BaseModel):
    raw: str
    fields: dict[str, str]
    # UNCHANGED from Phase 1 -- DP-003 Decision 5.

class BarcodeQrResult(BaseModel):
    raw: str
    fields: dict[str, str] = {}
    symbology: str | None = None   # NEW -- DP-003 Decision 6
```

`core/document/types.py` — `MRZExtraction`/`BarcodeExtraction` themselves are unchanged/minimally changed and carry only extracted data, per DP-003 Decisions 5/6:
```python
@dataclass(frozen=True)
class MRZExtraction:
    raw: str
    fields: dict[str, str]
    # UNCHANGED from Phase 1 -- DP-003 Decision 5. Pure extracted data,
    # no outcome/status information -- see §3 for how outcome is now
    # expressed (revised after reconciliation).

@dataclass(frozen=True)
class BarcodeExtraction:
    raw: str
    fields: dict[str, str] = field(default_factory=dict)
    symbology: str | None = None   # NEW -- DP-003 Decision 6, both layers per that decision's explicit text
```
Four new domain types are added alongside them (`MRZReadOutcome`, `MRZReadResult`, `BarcodeReadOutcome`, `BarcodeReadResult`) — see §3 for the full design and rationale; these are what actually changed as a result of reconciliation on this draft, replacing an earlier sentinel-value approach that was rejected.

`core/evidence_result/classification.py` — no change. `MRZ`/`BARCODE_QR` are already `HIGHLY_SENSITIVE` since Phase 1 (DP-001 Decision 1); DP-003 Decision 10 confirmed no reassessment is warranted.

**`fields: dict[str, str]` is a Phase 2 source-specific extraction representation, not a canonical identity/document schema — restating DP-001 Decision 7 and DP-003 Decision 5 directly, not deciding anything new.** `MRZ`/`BARCODE_QR`/`OCR_EXTRACTION` are frozen as "source-specific, non-canonical extraction representations"; the one canonical, cross-source representation is `DOCUMENT_FIELD_EXTRACTION`'s already-frozen hybrid schema (`full_name`, `surname`, `given_names`, `date_of_birth`, `sex`, `document_number`, `nationality`, `expiry_date`, plus an `extensions` map) — out of scope for this phase (DP-003 Decision 11). No code in this plan should be written as though `MrzResult.fields`/`BarcodeQrResult.fields` were, or were becoming, that canonical schema.

---

## 2. Reason codes

`core/document/reason_codes.py`, extending `DocumentReasonCode` (DP-003 Decision 3):
```python
class DocumentReasonCode(StrEnum):
    DOCUMENT_UNSUPPORTED = "DOCUMENT_UNSUPPORTED"
    IMAGE_TOO_BLURRY = "IMAGE_TOO_BLURRY"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    AMBIGUOUS_DOCUMENT_CAPTURE = "AMBIGUOUS_DOCUMENT_CAPTURE"
    MRZ_UNREADABLE = "MRZ_UNREADABLE"                              # NEW
    MRZ_MALFORMED = "MRZ_MALFORMED"                                # NEW
    MRZ_CHECK_DIGIT_MISMATCH = "MRZ_CHECK_DIGIT_MISMATCH"          # NEW
    BARCODE_UNREADABLE = "BARCODE_UNREADABLE"                      # NEW
    BARCODE_PAYLOAD_UNRECOGNIZED = "BARCODE_PAYLOAD_UNRECOGNIZED"  # NEW
    BARCODE_PAYLOAD_MALFORMED = "BARCODE_PAYLOAD_MALFORMED"        # NEW
```
`MODEL_UNAVAILABLE`/`AMBIGUOUS_DOCUMENT_CAPTURE` reused unchanged.

---

## 3. Expressing pipeline outcome — explicit wrapper type, not inferred from payload shape

**This is the one genuinely new, narrow choice this plan has to make — flagged explicitly, not silently decided.** The first draft of this section proposed inferring outcome from `raw`/`fields`' emptiness plus a synthetic `fields["_valid"]` sentinel key. That draft was rejected during reconciliation: it turned `fields` into simultaneously extracted data and control metadata, made empty `raw` load-bearing and ambiguous, and coupled outcome semantics to payload shape in a way a future real adapter could reproduce incorrectly by accident. Semantic state must be explicit, not inferred from accidental shape — this section replaces it.

**Revised design:** `MRZExtraction`/`BarcodeExtraction` stay exactly as DP-003 Decisions 5/6 froze them — pure extracted data, nothing else. Each capability's return type gains an explicit outcome wrapper that states what happened, rather than requiring `DocumentProcessor` to infer it:

```python
# core/document/types.py -- new types, added alongside the unchanged
# MRZExtraction/BarcodeExtraction from §1.

class MRZReadOutcome(StrEnum):
    """Explicit domain-level pipeline outcome for one MRZ zone-detection
    attempt. Deliberately NOT EvidenceResultStatus -- core/document/ MUST
    NOT import or produce EvidenceResultStatus directly (DP-001 Decision
    3's domain/persistence boundary); DocumentProcessor is solely
    responsible for translating this into an EvidenceResultStatus +
    reason code, via the explicit table in §6, not by inference."""
    UNREADABLE = "UNREADABLE"
    MALFORMED = "MALFORMED"
    CHECK_DIGIT_MISMATCH = "CHECK_DIGIT_MISMATCH"
    VALID = "VALID"


@dataclass(frozen=True)
class MRZReadResult:
    """Returned by MRZParser.parse() whenever a zone was found at all
    (parse() still returns bare None for "no zone present whatsoever" --
    unchanged, -> NOT_SUBMITTED). `extraction` is None exactly when
    outcome=UNREADABLE (nothing meaningful was extracted to wrap);
    populated for MALFORMED (raw text, no parsed fields), CHECK_DIGIT_
    MISMATCH, and VALID (raw text plus parsed fields in both cases --
    MALFORMED vs CHECK_DIGIT_MISMATCH is never distinguished by whether
    fields is populated, only by outcome)."""
    outcome: MRZReadOutcome
    extraction: MRZExtraction | None


class BarcodeReadOutcome(StrEnum):
    UNREADABLE = "UNREADABLE"
    PAYLOAD_UNRECOGNIZED = "PAYLOAD_UNRECOGNIZED"
    PAYLOAD_MALFORMED = "PAYLOAD_MALFORMED"
    VALID = "VALID"
    # No FAIL-equivalent member exists -- DP-003 Decision 2 forbids
    # BARCODE_QR from ever reaching FAIL; there is no outcome for
    # DocumentProcessor to map to it even if it tried.


@dataclass(frozen=True)
class BarcodeReadResult:
    outcome: BarcodeReadOutcome
    extraction: BarcodeExtraction | None   # None exactly when outcome=UNREADABLE
```

Capability signatures change to return these wrappers instead of the bare extraction type:

```python
class MRZParser(ABC):
    @abstractmethod
    async def parse(self, image: bytes) -> MRZReadResult | None:
        """None = no MRZ zone present at all -> MRZ=NOT_SUBMITTED. A
        populated MRZReadResult explicitly states what happened
        attempting to read/parse/validate whatever zone was found --
        DocumentProcessor never infers this from extraction's shape."""

class BarcodeDecoder(ABC):
    @abstractmethod
    async def decode(self, image: bytes) -> BarcodeReadResult | None:
        """None = no barcode/QR symbol present at all -> BARCODE_QR=NOT_SUBMITTED."""
```

This keeps the exact division of responsibility DP-001 Decision 3 established: the capability is the only party that actually performed structural parsing and check-digit validation, so it is the party that states the outcome explicitly, as domain vocabulary (`MRZReadOutcome`) — never as `EvidenceResultStatus`, which stays `DocumentProcessor`'s exclusive concern (§6's table). `MRZExtraction`/`BarcodeExtraction` remain pure extracted-data objects with zero control metadata, satisfying the concern that raised this revision.

**Capability contract principle (generalizing what `MRZParser`/`BarcodeDecoder`'s docstrings already state individually, not a new rule):**

> Where a capability port has an `Optional` return type, `None` means that the capability found no applicable input/presence to process; it is a legitimate outcome and never represents failure. Capabilities whose domain necessarily applies to every submitted capture need not use an optional return.

`QualityAssessor.assess()`/`DocumentClassifier.classify()` are the existing example of the second sentence — neither is `Optional`, because "quality" and "classification" apply to any `DOCUMENT` capture unconditionally; there is no "quality doesn't apply here" case the way there is a "no MRZ zone on this document" case. This principle is stated here because it is exactly the kind of contract a future capability outside Document Intelligence would need to follow consistently — but this document does not extend it to any capability beyond `MRZParser`/`BarcodeDecoder`.

---

## 4. `MRZParser` implementation

`core/document/deterministic.py`, extending the existing module:

```python
class DeterministicMRZParser(MRZParser):
    """Zone-detection/text-extraction is a stand-in (fixed test-marker
    driven, like DeterministicDocumentClassifier) -- structural TD1/TD2/
    TD3 parsing and ICAO 9303 check-digit validation are REAL, not faked
    (DP-003 Decision 8). A fake check-digit validator would misrepresent
    what this phase actually proves."""

    async def parse(self, image: bytes) -> MRZReadResult | None:
        marker_text = _extract_mrz_test_marker(image)   # stand-in zone-detection
        if marker_text is None:
            return None                                  # -> NOT_SUBMITTED
        if not marker_text:
            return MRZReadResult(outcome=MRZReadOutcome.UNREADABLE, extraction=None)
        parsed = parse_icao9303_structure(marker_text)     # REAL structural parse
        if parsed is None:
            return MRZReadResult(
                outcome=MRZReadOutcome.MALFORMED,
                extraction=MRZExtraction(raw=marker_text, fields={}),
            )
        valid = validate_check_digits(parsed)               # REAL ICAO 9303 algorithm
        return MRZReadResult(
            outcome=MRZReadOutcome.VALID if valid else MRZReadOutcome.CHECK_DIGIT_MISMATCH,
            extraction=MRZExtraction(raw=marker_text, fields=parsed.fields),
        )
```

`parse_icao9303_structure()` and `validate_check_digits()` are real, standalone, unit-testable functions (new module, `core/document/mrz.py`, kept separate from the deterministic-stub concern so the real ICAO 9303 logic reads as what it is — not bundled inside a file whose other contents are explicitly non-representative). Structural parse covers TD3 (passports — the only MRZ-bearing V1 catalog member per DP-001 Decision 5) at minimum; TD1/TD2 support is not required by the frozen document catalog but the function signature should not preclude adding them later. Check-digit validation implements ICAO Doc 9303's weighted 7-3-1 modulo-10 algorithm over document number, date of birth, expiry date, and the composite check digit, exactly as the standard defines it.

**`_extract_mrz_test_marker()`** — the actual test-double mechanism, analogous to Phase 1's `_CLASSIFICATION_MARKERS` byte-scan: fixture bytes carry a marker like `PAXLI_TEST_MRZ:<raw 44-char TD3 MRZ text>`, `PAXLI_TEST_MRZ_UNREADABLE`, or no marker at all. Returns `None` (no marker), `""` (unreadable marker), or the raw text following a valid-MRZ marker. This function is Phase 2's only non-representative stand-in for MRZ; everything downstream of it is real.

---

## 5. `BarcodeDecoder` implementation

```python
class DeterministicBarcodeDecoder(BarcodeDecoder):
    """Fully stand-in -- no real symbology-decode logic (DP-003 Decision
    8), mirroring DeterministicDocumentClassifier's pattern exactly. Real
    decoding is deferred to a future real-adapter phase."""

    async def decode(self, image: bytes) -> BarcodeReadResult | None:
        marker = _extract_barcode_test_marker(image)
        if marker is None:
            return None                                            # -> NOT_SUBMITTED
        if marker.raw == "":
            return BarcodeReadResult(outcome=BarcodeReadOutcome.UNREADABLE, extraction=None)
        if not marker.recognized_schema:
            return BarcodeReadResult(
                outcome=BarcodeReadOutcome.PAYLOAD_UNRECOGNIZED,
                extraction=BarcodeExtraction(raw=marker.raw, symbology=marker.symbology),
            )
        return BarcodeReadResult(
            outcome=BarcodeReadOutcome.VALID if marker.valid else BarcodeReadOutcome.PAYLOAD_MALFORMED,
            extraction=BarcodeExtraction(
                raw=marker.raw, symbology=marker.symbology, fields=marker.fields,
            ),
        )
```

`_extract_barcode_test_marker()` — same fixture-marker convention, driving all five outcome states deterministically. `symbology` is populated on `BarcodeExtraction` in every branch where `extraction` is non-`None` (`PAYLOAD_UNRECOGNIZED`, `PAYLOAD_MALFORMED`, `VALID`), using the normalized vocabulary from DP-003 Decision 6 (`QR_CODE`, `PDF417`, `CODE128`, etc.). `UNREADABLE` carries no `extraction` at all (per `BarcodeReadResult`'s own contract, §3), so symbology is not captured for that state in Phase 2 — a symbol that couldn't be decoded well enough to classify hasn't necessarily been identified well enough to name its symbology either, and preserving a partial `BarcodeExtraction(raw="", symbology=..., fields={})` for that one case would reintroduce exactly the "is an empty field meaningful or not" ambiguity §3 exists to eliminate.

**Marker-mechanism safety boundary.** `_extract_mrz_test_marker()`/`_extract_barcode_test_marker()` run against real, attacker-controlled document bytes in production (Phase 1's `DeterministicQualityAssessor`/`DeterministicDocumentClassifier` were wired into real DI, not test-only, per DP-002 §5 — Phase 2's stand-ins are wired the same way, §7). Two existing-precedent properties, restated, not new: absent/non-marker input yields no applicable marker (`None`, feeding `NOT_SUBMITTED`), never an exception — exactly how `DeterministicDocumentClassifier` already behaves (no marker found → `document_type=None`, no raise); malformed marker content must not cause an uncontrolled exception either. One new explicit requirement, not previously stated anywhere: marker recognition MUST match only the exact literal marker prefix (e.g. `PAXLI_TEST_MRZ:`) — arbitrary document bytes MUST NOT be interpreted as a marker instruction under any fuzzy/partial-match condition. Both marker functions are private implementation scaffolding for the deterministic stand-ins (DP-003 Decision 8) — they are NOT part of `MRZParser`/`BarcodeDecoder`'s externally observable contract, and a future real adapter implementing those same ABCs has no obligation to recognize, preserve, or be compatible with this marker format in any way. HV-011 (§9) retains the adversarial case this implies: crafted document bytes designed to spuriously trigger or evade marker matching.

---

## 6. `DocumentProcessor` extension

`infrastructure/document/processor.py`. Two new stages, added to `process()`'s existing sequential list, after classification:

```python
await self._run_quality(...)          # unchanged
await self._run_classification(...)   # unchanged
await self._run_mrz(...)              # NEW
await self._run_barcode(...)          # NEW
```

Both new `_run_*` methods follow the exact shape `_run_quality`/`_run_classification` already established (own session, existing-effective check via `_is_reusable`, ambiguous-capture short-circuit, `CapabilityUnavailableError` catch, `_persist_stage`, commit) — no new orchestration pattern. Status/reason-code derivation is now a direct lookup against an explicit, exhaustive table encoding DP-003 §7's frozen mapping literally — no branching on payload shape.

**`EvidenceResult.result=None` semantics — restating existing frozen behavior explicitly, not introducing a new rule.** Three distinct situations, each already settled by an existing decision, not by this plan:
- **Zero `DOCUMENT` captures for the session at all** → `DocumentProcessor.process()` returns before any stage runs; no `EvidenceResult` row is produced for `MRZ`/`BARCODE_QR` or any other type (DP-001 Decision 4 / DP-002 §4's existing "absence is the Decision Engine's concern, not this method's" precondition — unchanged, not re-decided here).
- **A capture exists, the stage runs, the capability reports no applicable zone/symbol** (`MRZParser.parse()`/`BarcodeDecoder.decode()` return `None`) → a real `EvidenceResult` row IS persisted, `status=NOT_SUBMITTED`, `result=None`. This is required, not optional, by DP-003 Decision 9's already-frozen reusability claim: a "terminal/reusable" `NOT_SUBMITTED` status is only meaningful if a persisted row exists for `get_effective_for_session_by_type()` to find on a later retry — `_is_reusable`'s short-circuit has nothing to check otherwise.
- **The stage runs, the capability engages and produces `MRZReadOutcome.UNREADABLE`** → a real `EvidenceResult` row is persisted, `status=INCONCLUSIVE`, `result=None` (no `extraction` to persist, §3). This is the case `result=None` most directly enables: `EvidenceResult` does not require a positive extraction payload to exist — the stage's own outcome and reason code fully represent what happened, with an absent payload being informative in its own right, not a gap.

Every other outcome (`MALFORMED`/`CHECK_DIGIT_MISMATCH`/`VALID` for MRZ; the equivalent three for Barcode/QR) persists a populated `result`.

```python
_MRZ_OUTCOME_MAP: dict[MRZReadOutcome, tuple[EvidenceResultStatus, str | None]] = {
    MRZReadOutcome.UNREADABLE: (EvidenceResultStatus.INCONCLUSIVE, DocumentReasonCode.MRZ_UNREADABLE.value),
    MRZReadOutcome.MALFORMED: (EvidenceResultStatus.INCONCLUSIVE, DocumentReasonCode.MRZ_MALFORMED.value),
    MRZReadOutcome.CHECK_DIGIT_MISMATCH: (EvidenceResultStatus.FAIL, DocumentReasonCode.MRZ_CHECK_DIGIT_MISMATCH.value),
    MRZReadOutcome.VALID: (EvidenceResultStatus.PASS, None),
}
# _BARCODE_OUTCOME_MAP (§6 prose below) carries the identical
# dict[BarcodeReadOutcome, tuple[EvidenceResultStatus, str | None]]
# annotation, for the same reason -- its VALID entry is also (PASS, None).
# A dedicated unit test iterates MRZReadOutcome's members and asserts every
# one has a map entry -- exhaustiveness is enforced, not assumed, so a
# future new outcome member can't silently fall through un-mapped.

async def _run_mrz(self, *, session_id, tenant_id, capture_id, object_key, ambiguous, request_id, correlation_id) -> None:
    async with self._session_factory() as session:
        service = self._build_evidence_result_service(session)
        existing = await service.get_effective_for_session_by_type(
            session_id=session_id, tenant_id=tenant_id, evidence_type=EvidenceResultType.MRZ,
        )
        if existing is not None and _is_reusable(existing.status):
            return
        if ambiguous:
            await self._persist_stage(..., status=INCONCLUSIVE,
                                       reason_codes=(DocumentReasonCode.AMBIGUOUS_DOCUMENT_CAPTURE.value,))
            await session.commit()
            return

        image = await self._storage.get(object_key)
        try:
            read_result = await self._mrz_parser.parse(image)
        except CapabilityUnavailableError as exc:
            await self._persist_stage(..., status=UNAVAILABLE, reason_codes=(exc.reason_code,),
                                       source_reference=capture_id)
            await session.commit()
            return

        if read_result is None:
            await self._persist_stage(..., status=NOT_SUBMITTED, source_reference=capture_id)
        else:
            status, reason_code = _MRZ_OUTCOME_MAP[read_result.outcome]
            result_payload = (
                {"raw": read_result.extraction.raw, "fields": read_result.extraction.fields}
                if read_result.extraction is not None else None
            )
            await self._persist_stage(
                ..., status=status,
                reason_codes=(reason_code,) if reason_code else (),
                result=result_payload,
                source_reference=capture_id,
            )
        await session.commit()
```

`_run_barcode` is structurally identical, with `BarcodeDecoder`/`BARCODE_QR`/`BarcodeReadOutcome` substituted and `result` including `"symbology": read_result.extraction.symbology` alongside `raw`/`fields` whenever `extraction is not None`, against its own explicit table (written out in full, not left as "structurally identical" shorthand, so every state is visibly mapped exactly once against DP-003 §7):

```python
_BARCODE_OUTCOME_MAP: dict[BarcodeReadOutcome, tuple[EvidenceResultStatus, str | None]] = {
    BarcodeReadOutcome.UNREADABLE: (EvidenceResultStatus.INCONCLUSIVE, DocumentReasonCode.BARCODE_UNREADABLE.value),
    BarcodeReadOutcome.PAYLOAD_UNRECOGNIZED: (EvidenceResultStatus.INCONCLUSIVE, DocumentReasonCode.BARCODE_PAYLOAD_UNRECOGNIZED.value),
    BarcodeReadOutcome.PAYLOAD_MALFORMED: (EvidenceResultStatus.INCONCLUSIVE, DocumentReasonCode.BARCODE_PAYLOAD_MALFORMED.value),
    BarcodeReadOutcome.VALID: (EvidenceResultStatus.PASS, None),
}
```

`_BARCODE_OUTCOME_MAP` has no `EvidenceResultStatus.FAIL` value anywhere in it — `BarcodeReadOutcome` has no member corresponding to one (§3), so there is no code path, not merely a convention, by which `BARCODE_QR` could reach `FAIL`.

No sentinel inspection, no payload-shape inference, and no filtering step — `read_result.extraction`'s `raw`/`fields`[/`symbology`] map directly onto `MrzResult`/`BarcodeQrResult` with nothing to strip, since `MRZReadOutcome`/`BarcodeReadOutcome` (§3) never touch `fields` at all.

**Producer/provenance constants**, mirroring Phase 1's `_PRODUCER_QUALITY`/`_PRODUCER_CLASSIFIER`:
```python
_PRODUCER_MRZ = "document-mrz-parser-deterministic"
_PRODUCER_BARCODE = "document-barcode-decoder-deterministic"
```
`_PRODUCER_VERSION = "1.0"` reused unchanged.

**Constructor** gains two new required parameters:
```python
class SqlAlchemyDocumentProcessor:
    def __init__(
        self,
        session_factory, key_provider, key_id, storage,
        quality_assessor: QualityAssessor,
        document_classifier: DocumentClassifier,
        mrz_parser: MRZParser,           # NEW
        barcode_decoder: BarcodeDecoder, # NEW
    ) -> None: ...
```

---

## 7. Workflow / DI wiring

`apps/api/paxli_api/dependencies.py`'s `get_workflow_service()` gains the corresponding construction: `DeterministicMRZParser()`/`DeterministicBarcodeDecoder()` passed alongside the existing two deterministic capabilities. `core/verification/workflow.py` is untouched — `document_processor.process()` is already called unconditionally from the `PROCESSING` branch (DP-001 Decision 4); the two new stages ride inside `process()`'s own internal sequence, invisible to `VerificationWorkflowService`.

Every existing test that constructs `SqlAlchemyDocumentProcessor`/`get_workflow_service()` directly (`tests/integration/test_document_processor.py`, `test_submit_api_wiring.py`, `test_verification_workflow.py`) needs its construction call updated with the two new required arguments — the same class of mechanical breakage DP-002's Phase 1 rollout already went through once (direct-call sites bypassing `Depends()` resolution), so expect it, don't treat it as a surprise regression when it happens.

---

## 8. Testing strategy

- **`tests/unit/`**: `parse_icao9303_structure()`/`validate_check_digits()` get thorough standalone coverage — this is real logic, not a stand-in, and deserves the positive/negative/edge-case rigor that implies (valid TD3 MRZ, single-digit check failure per field, all-digits-failing, malformed length, invalid character set, composite check digit specifically). `DeterministicMRZParser`/`DeterministicBarcodeDecoder` get a test per §3's outcome branches each, confirming the right `MRZReadOutcome`/`BarcodeReadOutcome` and `extraction` shape comes back for each marker. `_MRZ_OUTCOME_MAP`/`_BARCODE_OUTCOME_MAP` (§6) each get an exhaustiveness test (every enum member has a map entry) and a direct assertion that no `BarcodeReadOutcome` maps to `EvidenceResultStatus.FAIL`.
- **`tests/integration/`** (real Postgres + MinIO): full round-trip producing real `MRZ`/`BARCODE_QR` rows for each of the four/five outcome states per capability, correct `source_reference` lineage; retry-convergence covering BOTH directions, not just one — an `UNAVAILABLE` MRZ result superseded by a real attempt (mirroring Phase 1's existing test), AND a call-count assertion (mirroring `test_retry_does_not_recompute_an_already_reusable_result`) proving a second `process()` call does NOT re-invoke `MRZParser`/`BarcodeDecoder` once any terminal/reusable status (`PASS`, `FAIL`, `INCONCLUSIVE`, `NOT_SUBMITTED` per DP-003 Decision 9) has already been recorded; a real two-`DOCUMENT`-capture ambiguity test extended to cover the two new stages; a structurally-valid-but-check-digit-mismatched MRZ document producing `MRZ=FAIL` while `DOCUMENT_QUALITY`/`DOCUMENT_CLASSIFICATION` remain unaffected (partial-stage independence, mirroring the existing unrecognized-document test); a full `/submit`-driven policy test mirroring Phase 1's `test_document_unsupported_lets_policy_not_document_processor_decide_outcome` exactly — two policies, identical `MRZ`/`BARCODE_QR` evidence, two different final outcomes, proving §12's "a policy can require and condition on either type today" claim is actually demonstrated, not merely asserted.
- **`tests/contracts/`**: `BARCODE_QR` never producing `FAIL` under any tested input — a direct, explicit assertion this constraint holds, not just an absence of counter-examples.
- **Concurrency**: extend HV-010's existing concurrent-`process()`/concurrent-`submit()` tests to a four-stage `process()` call, confirming `EffectiveResultAlreadyExistsError`'s convergence (already generic, HV-010) holds for `MRZ`/`BARCODE_QR`'s new call sites specifically — not assumed from the fact the underlying fix is generic.

---

## 9. HV-011 attack surface (preview only — not run from this document)

Once Phase 2 lands: crafted/adversarial MRZ text (SEC-7.21) fed through the real structural parser and check-digit validator — oversized input, non-ASCII/unexpected Unicode in a fixed-charset field, boundary-length strings; document bytes crafted to spuriously trigger or evade `_extract_mrz_test_marker()`/`_extract_barcode_test_marker()`'s exact-prefix matching (§5's marker-mechanism safety boundary) — confirming a real document containing incidental substrings resembling the marker format is never misinterpreted, and confirming malformed/truncated marker content degrades to `None`/`NOT_SUBMITTED` rather than an uncontrolled exception; tenant isolation re-confirmed at the two new stages specifically (mirroring HV-010's `test_wrong_tenant_id_...` pattern); the concurrent-race class HV-010 found and fixed, re-attacked at these two new call sites rather than assumed safe by inheritance; confirmation that `_run_mrz`/`_run_barcode`'s unexpected-exception handling matches Phase 1's (`CapabilityUnavailableError` only, everything else propagates uncaught).

---

## 10. Dependency policy

**No new runtime dependency is added in Phase 2.** The real ICAO 9303 check-digit algorithm is pure arithmetic (weighted modulo-10 sum) requiring no library; both deterministic stand-ins (`DeterministicMRZParser`'s zone-detection, `DeterministicBarcodeDecoder` entirely) are fixture-marker-driven, requiring no OCR, computer-vision, or symbology-decoding library. `pyproject.toml` is untouched. This is consistent with DP-001's own boundary (real library selection is deferred to whichever future phase builds a real, non-deterministic adapter) and DP-003 §1's explicit exclusion of library selection from this vertical slice's discovery/planning scope.

---

## 11. Explicit non-goals for Phase 2

- No real (non-deterministic) MRZ zone-detection/OCR or barcode symbology decoding — both remain fixture-marker stand-ins per §4/§5; only MRZ check-digit validation is real (§4).
- No `OCREngine` implementation (still deferred, DP-003 §1).
- No `DOCUMENT_FIELD_EXTRACTION` reconciliation algorithm (DP-003 Decision 11).
- No `AuthenticityChecker` (DP-001 Decision 6, unchanged).
- No confidence/quality scoring on `MrzResult`/`BarcodeQrResult` (DP-003 Decision 4).
- No ICAO 9303 canonical field breakdown surfaced through `MRZ`'s own schema (DP-003 Decision 5) — `fields` stays informal.
- No `DocumentType -> {has_mrz, has_barcode}` capability-flag mapping (DP-003 Decision 7) — absence-weighting is a policy concern.
- No `CircuitBreaker`/`RetryPolicy`/timeout wrapper around the new capability calls — same reasoning as Phase 1 (`DP-002 §4`): deterministic, in-process, pure functions have nothing genuine to circuit-break against yet.
- No changes to `VerificationWorkflowService`, `DecisionOrchestrator`, `core/policy/`, or any WF/DE/HV-frozen contract.
- No new runtime dependency (§10).

---

## 12. Closure criteria

Phase 2 is done when: `DocumentProcessor` produces real, correctly-lineaged `MRZ`/`BARCODE_QR` `EvidenceResult` rows across every outcome state in DP-003 §7's frozen table, the real ICAO 9303 check-digit validator is independently unit-tested to standards-conformant correctness, `BARCODE_QR` is confirmed by direct test to never emit `FAIL`, a policy can require and condition on either type today through the unmodified Decision Engine, retried `/submit` calls converge without re-invoking already-satisfied stages, the full test suite passes twice consecutively, mypy/ruff are clean, and a scoped HV-011 pass against exactly this new surface (§9) comes back clean or with findings triaged the same way every HV-00X finding has been this session — fixed, disclosed, or explicitly deferred, never silently ignored.
