# DP-003 — Document Processing Phase 2 Discovery & Reconciliation (MRZ + Barcode/QR)

**Status:** RECONCILIATION COMPLETE — all 11 decisions frozen (§9). No production code has been changed during discovery or reconciliation. Implementation is NOT yet authorized: per the DP-001 → DP-002 precedent, a companion implementation plan (DP-004) locks the concrete engineering shape from these frozen decisions before any code is written.
**Scope:** the second real document-processing capability pair — `MRZParser` and `BarcodeDecoder` — building on the deterministic Quality/Classification foundation DP-002 shipped and HV-010 hardened.
**Method:** full trace of `docs/specification/` for every MRZ/Barcode/QR-relevant requirement, plus a full repository inventory of everything DP-001/DP-002 already put in place for these two capabilities specifically (interfaces, domain types, schemas, classification, reason codes, orchestrator wiring). Citations below are `file:line` where available.
**Precedent:** DP-001's 7 frozen decisions are binding architecture this document does not relitigate except where explicitly noted. This document exists only to resolve what DP-001 deliberately left open for MRZ/Barcode specifically (its own §14 Open Question 8, and the "MAY be interface-designed... MUST NOT receive production implementations" holding pattern in Decision 3).

## Reconciliation log

| # | Decision | Status |
|---|---|---|
| 1 | MRZ status vocabulary & malformed-vs-invalid semantics | **FROZEN, AMENDED** — see §9 |
| 2 | Barcode/QR status vocabulary & malformed-payload semantics | **FROZEN, AMENDED** — see §9 |
| 3 | Reason codes for MRZ/Barcode failure modes | **FROZEN, EXPANDED** — see §9 |
| 4 | Confidence/quality scoring for MRZ/Barcode extraction | **FROZEN** — see §9 |
| 5 | MRZ result schema shape (ICAO 9303 field breakdown) | **FROZEN** — see §9 |
| 6 | Barcode/QR result schema shape (symbology field) | **FROZEN, AMENDED** — see §9 |
| 7 | Absence semantics & orchestration invocation | **FROZEN** — see §9 |
| 8 | Deterministic implementation shape for Phase 2 | **FROZEN** — see §9 |
| 9 | Reusable-vs-retryable matrix extension | **FROZEN** — see §9 |
| 10 | Sensitivity classification reassessment | **FROZEN — no change** — see §9 |
| 11 | `DOCUMENT_FIELD_EXTRACTION` reconciliation — explicitly OUT of DP-003 | **FROZEN — excluded** — see §9 |

### Governing principle established during reconciliation

> **A capability MUST only emit `FAIL` when it has actually established the defined negative condition for its evidence type. Inability to read, locate, parse, or interpret data is `INCONCLUSIVE`, not `FAIL`.**

This governs Decisions 1 and 2 directly and is stated once here because it is the single most consequential correction reconciliation made to this document's original draft: the draft's proposed handling of structurally malformed MRZ (reject before persistence, mirroring OCR's malformed-output precedent) would have discarded observable evidence of a real processing outcome. Persisting it as `INCONCLUSIVE` with a specific reason code instead keeps technical uncertainty ("couldn't read it," "couldn't parse it") legible and distinct from an actual negative finding ("read it, and it's wrong") — exactly the distinction this project's constitution already draws between infrastructure failure and identity failure, applied here one level down, inside a single capability's own outcome space.

---

## 1. Scope

In scope: everything needed to take a `DOCUMENT_CLASSIFICATION`-classified capture through MRZ parsing and Barcode/QR decoding into real `MRZ`/`BARCODE_QR` `EvidenceResult` rows — without reopening DP-001's frozen architecture (capability-port shape, lineage model, synchronous processing boundary, document catalog, authenticity scope) and without touching `OCREngine` or `DOCUMENT_FIELD_EXTRACTION` reconciliation.

Out of scope, explicitly:
- **OCR** (`OCREngine`/`OCR_EXTRACTION`) — deferred to its own phase (tentatively "DP-004/Phase 3" per the session's revised roadmap), not because it's less important, but because MRZ and Barcode/QR are independently-consumable capabilities that don't need OCR to exist first, and bundling three new capabilities into one Discovery would blur exactly the kind of hostile-validation surface HV-010 just proved is worth isolating narrowly.
- **`DOCUMENT_FIELD_EXTRACTION` reconciliation** — DP-001 Decision 7 already froze this evidence type's *schema shape*, but the reconciliation *algorithm* it explicitly left open ("normalization, conflict resolution, name-component derivation... a separate, unresolved architectural item") depends on having all three upstream sources (OCR, MRZ, Barcode/QR) to reconcile *across*. With OCR still unbuilt, a real three-way reconciliation cannot be designed honestly in this phase. Recommend treating this as its own future discovery once OCR lands, rather than a partial two-source (MRZ+Barcode only) reconciliation that would need to be redesigned the moment OCR arrives. This is Decision 11 below — flagged for your explicit confirmation since DP-001's own original phase plan (§17) bundled field reconciliation into the same phase as MRZ/Barcode, and this document proposes splitting it out.
- **`DOCUMENT_AUTHENTICITY`** — DP-001 Decision 6 (frozen) already forecloses this for the entire V1 vertical slice; restated here only to head off the specific mistake Decision 6 already named (mistaking MRZ check-digit success for an authenticity signal).
- Real library selection/integration — this discovery produces the semantic contract (status vocabulary, schema shape, reason codes, failure mapping) the deterministic Phase 2 implementation and any eventual real adapter must both honor; it does not choose an OCR-for-MRZ engine or a barcode-decoding library.

---

## 2. The headline finding — the spec has almost nothing to say about these two capabilities specifically

Unlike DP-001's headline finding (a genuine spec/implementation classification conflict), DP-003's headline finding is different in kind: **a full-text search of every file in `docs/specification/` for "MRZ", "Machine-Readable Zone", "Barcode", "QR", "check digit", "ICAO", and "PDF417" returns exactly one substantive hit** — the §3.5 taxonomy diagram (`part-03-evidence-semantics.md:101`) naming `MRZ` and `Barcode/QR` as two sibling leaves:

```
|- Document: DocumentQuality, DocumentClassification, OCRExtraction,
|            DocumentFieldExtraction, MRZ, Barcode/QR, DocumentAuthenticity
```

That is the entire normative footprint. No section differentiates MRZ from Barcode/QR, defines a status vocabulary for either, references ICAO 9303, mentions a check-digit concept, or names a barcode symbology. Every other requirement that bears on these two capabilities is a *generic* evidence/workflow/decision/security/privacy requirement that applies to them only by virtue of applying to every evidence type uniformly (§3 below).

**Consequence for this document's shape:** DP-003 cannot be "trace the spec, find what MRZ/Barcode require, implement it" the way DP-001 could partially do for the broader taxonomy. Instead, most of what Phase 2 needs is either (a) architecture DP-001 already froze and this phase inherits unchanged, or (b) genuinely undefined by the specification and must be an explicit PaxLI-originated decision, grounded in the generic requirements that do apply (EVD-3.6's domain-specific-label allowance, EVD-3.24's malformed-evidence safety net, REL-10.21's malformed-model-output handling) rather than in any MRZ/Barcode-specific text, because none exists.

This also means the user's instruction not to assume MRZ and Barcode/QR need identical treatment is not just good practice — it's *necessary*, because the spec offers no default to fall back on for either capability individually, let alone a reason to treat them as a matched pair. §6 below makes the case for where they should diverge.

---

## 3. Normative requirement matrix

Every requirement below is generic (applies to all evidence types), evaluated specifically for MRZ/Barcode-QR consequences. Requirements DP-001 already resolved generically (and which need no fresh reasoning here) are marked **[inherited, no new work]**.

### Part III — Evidence Semantics

| Requirement | Consequence for MRZ/Barcode-QR |
|---|---|
| EVD-3.2 (Definition of Evidence) | **[inherited, no new work]** — same shape as every `EvidenceResult`. |
| EVD-3.5.2 ("Evidence types MUST have defined semantics before being accepted by the Decision Engine") | **Not yet satisfied for MRZ/Barcode.** The taxonomy names them; nothing defines their status vocabulary or result semantics. This is what Decisions 1–2 below must supply. |
| EVD-3.6 (closed status set; **domain-specific terminal labels MAY be used where materially different**, e.g. `MATCH`/`MISMATCH`) | The explicit license for MRZ to have a check-digit-specific outcome distinct from generic `FAIL`, if warranted — not a mandate either way. See Decision 1. |
| EVD-3.7 (six-state absence model; `FAIL` = "the component established the negative condition defined by its evidence type") | `FAIL`'s definition presupposes a defined "negative condition" per type — MRZ/Barcode don't have one yet. `NOT_SUBMITTED`'s example language ("a required document... never uploaded") is about the *capture*, not a zone/feature absent *within* a capture — DP-002 already extended it to "no MRZ zone detected" by implementation choice, not spec mandate. See Decision 7. |
| EVD-3.9 (Integrity), EVD-3.10 (Immutability) | **[inherited, no new work]** — AES-GCM-at-rest and supersession-on-retry already proven generically (HV-009), already schema-registered for `MRZ`/`BARCODE_QR`. |
| EVD-3.12 (quality thresholds must be policy-defined, not hardcoded) | Only bites if MRZ/Barcode get a confidence/quality concept at all — see Decision 4. |
| EVD-3.13 (scores need documented semantics; not a probability without calibration) | Same conditional as above. |
| EVD-3.14 (reason-code catalog: `IMAGE_TOO_BLURRY, FACE_NOT_DETECTED, MULTIPLE_FACES, MODEL_UNAVAILABLE, MODEL_TIMEOUT, OCR_UNREADABLE, DOCUMENT_UNSUPPORTED, PROVIDER_TIMEOUT, INSUFFICIENT_SIGNAL`) | **No MRZ- or Barcode-specific code exists in the spec's own example list.** A check-digit-failure code and a malformed-barcode-payload code are new PaxLI coinages either way. See Decision 3, and DP-001's still-open Open Question 3 (where evidence-level reason codes live in code — never resolved, carried forward). |
| EVD-3.17 (lineage — capture→result, result→result) | **[inherited, no new work]** — DP-001 Decision 2's wiring rule applies identically: `source_reference` to the capture for both, `parent_evidence_result_ids` unused unless a future stage consumes MRZ/Barcode output directly. |
| EVD-3.24 (invalid/malformed evidence → safe outcome, never persisted as trusted) | The anchor for **structurally malformed** MRZ/Barcode output specifically (as opposed to structurally-valid-but-negative, e.g. checksum fails). This is the sharpest gap in the whole document — see Decision 1/2 and §7. |
| EVD-3.25 (Evidence Conflicts — "MUST NOT be resolved through implicit precedence... belongs to the Decision Engine and applicable policy") | Directly relevant the moment MRZ and Barcode (and later OCR) disagree on the same field during eventual `DOCUMENT_FIELD_EXTRACTION` reconciliation — but that reconciliation is out of scope here (§1). Noted for continuity, not acted on. |
| EVD-3.29 (Access Boundaries / tenant isolation) | **[inherited, no new work]** — HV-010 already attacked this exact boundary at the `DocumentProcessor` level and confirmed it holds; nothing about MRZ/Barcode's content changes the mechanism. |
| EVD-3.34 (normative EvidenceResult shape) | **[inherited, no new work]** — `result`/`reason_codes`/`score`/`quality`/`producer`/`producer_version`/`model_reference` fields all apply identically; current `MrzResult`/`BarcodeQrResult` schemas already conform structurally (§4), just thinly. |

### Part IV — Verification Workflow

| Requirement | Consequence |
|---|---|
| WF-4.11/4.12 (processing execution states) | **[inherited, no new work]** — DP-001 Decision 4's ephemeral, non-persisted execution-state resolution applies unchanged; no new answer needed per capability. |
| WF-4.15 (retryable vs non-retryable failures must be distinguishable; retry exhaustion → `INCONCLUSIVE`) | Where DP-001's still-open reusable-vs-retryable matrix (§14 Open Question 8) actually needs an answer for MRZ/Barcode specifically — Phase 1 only resolved the narrow 2-capability deterministic instance. See Decision 9. |
| WF-4.16 (bounded timeout on every external/blocking operation) | Not yet actionable — no real library exists yet to time out. Relevant the moment a real adapter is built (later phase), noted for continuity. |

### Part V — Decision Engine

| Requirement | Consequence |
|---|---|
| DEC-5.1 (components MUST NOT independently declare a verdict) | **[inherited, no new work]** — structurally guaranteed by `DocumentProcessor`'s existing shape; a real `MRZParser`/`BarcodeDecoder` implementation has no path to bypass it. |
| DEC-5.7 (statuses MUST NOT be reinterpreted inconsistently across types) | Constrains Decision 1 below: if MRZ gets a domain-specific sub-status, it must still map cleanly onto the closed six-state model, not become a de facto seventh state the Decision Engine can't reason about. |
| DEC-5.14 (`EvidenceCondition` — unsupported properties MUST fail policy validation) | **[inherited limitation, not new]** — `MrzResult`/`BarcodeQrResult`'s raw `fields: dict[str,str]` shape means policy still cannot condition on `MRZ.fields.document_number` directly, the same nested-field-addressability gap DP-001 Decision 7 explicitly left unresolved for `MRZ`/`BARCODE_QR`/`OCR_EXTRACTION` (only `DOCUMENT_FIELD_EXTRACTION` got the flattened treatment). Not proposing to fix this now — noted so it isn't mistaken for a new Phase 2 gap. |

### Part VII — Security and Governance

| Requirement | Consequence |
|---|---|
| SEC-7.21 (adversarial input — malicious, malformed, oversized, contradictory, resource-exhausting) | Applies at the **parsed-content** layer, not just the file layer: a crafted MRZ line or a maliciously-encoded barcode payload is adversarial input in its own right, independent of `verify_evidence_media()`'s existing file-level checks. |
| SEC-7.22 (untrusted media; malformed media fails safe; **no filesystem/infrastructure exposure through attacker-controlled content**) | The library-selection threat-modeling requirement DP-001 §12 already flagged, now squarely this phase's responsibility once a real MRZ-OCR or barcode-decoding library is chosen (deferred beyond this discovery — see §1). Flagged here because the two capabilities' actual attack-surface shape differs (§6 point 5) even though the requirement text is identical for both. |

### Part IX — Deferred Architecture

| Capability | Status |
|---|---|
| MRZ, Barcode/QR themselves | **NOT deferred** — PREREQUISITE v1.0, confirmed by the same §3.5 citation DP-001 already used for the whole taxonomy. |
| DEF-9.15.2 ("Absence of authenticity capability MUST NOT be interpreted as authenticity success") | **[inherited, no new work]** — DP-001 Decision 6 already pre-empted the specific mistake this could invite (treating MRZ checksum-valid as authenticity-valid); restated as binding precedent, not reopened. |

### Part X — Reliability

| Requirement | Consequence |
|---|---|
| REL-10.15 (partial pipeline failure preserves completed evidence) | **[inherited, no new work]** — if MRZ fails but Barcode/QR succeeds (or vice versa), each stands as its own immutable row; structurally guaranteed already, proven generically in HV-010's own concurrency fix. |
| REL-10.21 (inference failure incl. **malformed output**; invalid model output MUST NOT become valid evidence) | The other anchor (alongside EVD-3.24) for the structurally-malformed-output question — see Decision 1/2. `validate_result_payload()` already rejects schema-invalid payloads at `create()` time; the open question is what counts as schema-invalid vs. schema-valid-but-negative for each capability. |

### Part XI — Data Protection and Privacy

| Requirement | Consequence |
|---|---|
| PRV-11.5 (Identity Data — names, DOB, ID numbers, nationality, address; `SENSITIVE` unless stricter applies) | MRZ raw/parsed content is, verbatim, an instance of this enumeration (ICAO 9303 MRZ lines encode name, document number, nationality, DOB, sex, expiry). Barcode/QR payloads on an identity document commonly encode the same attribute set, but — unlike MRZ — not *always* (an opaque reference/URL QR encodes none of it). This asymmetry is exactly what DP-001 Decision 1's own closing caveat already anticipated (quoted in full in §6 point 4). |
| PRV-11.7.6 (temporary processing copies must follow lifecycle/deletion rules) | Still open, exactly as DP-001 §12 left it — needs an answer once a specific MRZ-OCR or barcode-decoding library is chosen (does it write temp files?). Deferred beyond this discovery per §1. |

---

## 4. Existing implementation inventory

Everything DP-001/DP-002 already put in place for MRZ/Barcode-QR specifically, confirmed by direct repository inspection:

**Capability ports** (`core/document/capabilities.py`) — interface-only, explicitly docstring-flagged:
```python
class MRZParser(ABC):
    """No Phase 1 implementation -- interface only (DP-001 Decision 3)."""

    @abstractmethod
    async def parse(self, image: bytes) -> MRZExtraction | None:
        """None = no MRZ zone present -- a legitimate outcome
        (-> MRZ=NOT_SUBMITTED), never an error."""
        raise NotImplementedError


class BarcodeDecoder(ABC):
    """No Phase 1 implementation -- interface only (DP-001 Decision 3)."""

    @abstractmethod
    async def decode(self, image: bytes) -> BarcodeExtraction | None:
        """None = no barcode/QR present -> BARCODE_QR=NOT_SUBMITTED."""
        raise NotImplementedError
```

Note the structural divergence from Phase 1's two implemented ports already baked in: `MRZParser.parse`/`BarcodeDecoder.decode` return `Optional[...]` — absence is pushed to the method's return type — whereas `QualityAssessor.assess`/`DocumentClassifier.classify` always return a populated dataclass (absence-as-a-value lives *inside* the dataclass, e.g. `DocumentClassification.document_type: DocumentType | None`). This was already decided by whoever wrote DP-002's interfaces; this discovery inherits it as the shape to build against, but it directly shapes how `DocumentProcessor`'s existing `_run_quality`/`_run_classification`-style per-stage handler needs to branch for these two (a `None` check before any status-mapping logic even runs).

**Domain types** (`core/document/types.py`):
```python
@dataclass(frozen=True)
class MRZExtraction:
    """No Phase 1 producer exists for this type."""
    raw: str
    fields: dict[str, str]

@dataclass(frozen=True)
class BarcodeExtraction:
    """No Phase 1 producer exists for this type."""
    raw: str
    fields: dict[str, str] = field(default_factory=dict)
```
Identical shape to each other (only difference: `BarcodeExtraction.fields` has a default). Neither carries a confidence field, a check-digit-validity field, or (for barcode) a symbology field.

**EvidenceResult schemas** (`core/evidence_result/schemas.py`), already registered in `SCHEMA_REGISTRY` and enforced by `validate_result_payload()`:
```python
class MrzResult(BaseModel):
    raw: str
    fields: dict[str, str]

class BarcodeQrResult(BaseModel):
    raw: str
    fields: dict[str, str] = {}
```
Mirrors the domain types exactly. Already policy-queryable at the top-level-field granularity via `EvidenceResultSchemaCatalog` (generic over the registry, no MRZ/Barcode-specific logic needed there).

**Enum members** (`core/evidence_result/enums.py`) — `MRZ` and `BARCODE_QR` both present in `EvidenceResultType`. `DocumentType` (the frozen V1 catalog, DP-001 Decision 5) has exactly 3 members: `STANDARD_NIN_SLIP`, `IMPROVED_NIN_SLIP`, `ICAO_PASSPORT_DATA_PAGE`. Only `ICAO_PASSPORT_DATA_PAGE` is documented as MRZ-bearing (DP-001 Decision 5's own text, quoted in §6 point 3) — nothing in code encodes a per-`DocumentType` "has MRZ" / "has barcode" capability flag; it exists only as prose in a frozen decision record.

**Classification** (`core/evidence_result/classification.py`) — both already `HIGHLY_SENSITIVE`, per DP-001 Decision 1 (frozen). Governing test already exists and passes: `test_document_extraction_types_are_highly_sensitive_and_encrypted_at_rest` (added during HV-010), parametrized over `MRZ`/`BARCODE_QR`/`OCR_EXTRACTION`/`DOCUMENT_FIELD_EXTRACTION`, confirming the classification→encryption wiring is already proven correct for these exact schema shapes, before any real producer exists. This is meaningful pre-built safety net for Phase 2 — the encryption boundary does not need to be re-verified once a real implementation lands, only the *content* of what gets encrypted needs review if the schema shape changes (Decisions 5/6 below).

**Orchestrator** (`infrastructure/document/processor.py`, `SqlAlchemyDocumentProcessor`) — constructor currently injects only `quality_assessor: QualityAssessor` and `document_classifier: DocumentClassifier`; no `mrz_parser`/`barcode_decoder` parameters exist. `process()` calls `_run_quality`/`_run_classification` sequentially; no `_run_mrz`/`_run_barcode` methods exist. The reusable `_persist_stage` static helper (create-vs-supersede) and the ambiguous-capture short-circuit (computed once per `process()` call, shared across stages) are both directly reusable for new stages without modification. `_is_reusable()`'s current binary logic (`status is not UNAVAILABLE`) was never designed with a `None`-returning capability in mind — worth re-examining under Decision 9, though it plausibly still gives the right answer for `NOT_SUBMITTED` (terminal, like `PASS`/`FAIL`).

**Reason codes** (`core/document/reason_codes.py`) — 4 members: `DOCUMENT_UNSUPPORTED`, `IMAGE_TOO_BLURRY`, `MODEL_UNAVAILABLE`, `AMBIGUOUS_DOCUMENT_CAPTURE`. `AMBIGUOUS_DOCUMENT_CAPTURE` is directly reusable as-is (capture-level, not capability-specific). `MODEL_UNAVAILABLE` is plausibly reusable for `CapabilityUnavailableError`-driven `UNAVAILABLE` results from a real MRZ/Barcode implementation. **Nothing exists for check-digit failure, MRZ structural-malformation, or barcode-payload-malformation** — confirmed by whole-repo grep, zero matches for any MRZ/Barcode-specific reason code anywhere.

**Deterministic implementations** (`core/document/deterministic.py`) — `DeterministicQualityAssessor`/`DeterministicDocumentClassifier` exist, explicitly documented as non-representative stand-ins ("NOT a stand-in for real quality/classification models"). No deterministic `MRZParser`/`BarcodeDecoder` exists. See §6 point 6 for why this phase's deterministic-implementation question is not a straightforward copy of Phase 1's pattern.

**Dependencies** — `pyproject.toml` has no barcode/MRZ/image-processing library of any kind (no `pyzbar`, `zxing`, `mrz`/`python-mrz`, `pillow`, `opencv-python`). No lock file exists in the repo. Confirms Phase 2 starts from a clean dependency slate; library selection is fully open and explicitly out of this discovery's scope (§1).

**Test coverage** — zero MRZ/Barcode capability or orchestration tests exist anywhere. The only MRZ/Barcode-touching test in the whole suite is the encryption-boundary parametrized test noted above (persistence/classification layer only, not capability or pipeline behavior).

---

## 5. Existing reusable primitives

Everything Phase 1 and HV-010 already proved that Phase 2 gets for free, requiring zero new design work:

- Capability-port shape and `DocumentProcessor`'s translation responsibility (DP-001 Decision 3, already interface-designed for both `MRZParser`/`BarcodeDecoder`)
- Lineage wiring rule — `source_reference` to the capture (DP-001 Decision 2)
- Synchronous processing boundary inside `submit()`'s `PROCESSING` branch, before `evaluate_and_persist()` (DP-001 Decision 4)
- Per-stage independent session/commit, sequential (not `asyncio.gather()`) execution (DP-001 Decision 4's implementation note, empirically confirmed necessary during Phase 1)
- `CapabilityUnavailableError`-only exception taxonomy — any other exception propagates uncaught, never silently normalized (DP-002 reconciliation amendment B, directly HV-010-tested)
- Ambiguous-capture precondition handling, shared across stages (`AMBIGUOUS_DOCUMENT_CAPTURE`, DP-002 reconciliation amendment A)
- `_persist_stage`'s create-vs-supersede convergence logic, including the concurrent-create race protection HV-010 added (`EffectiveResultAlreadyExistsError`) — any new MRZ/Barcode stage calling into the same `EvidenceResultService.create()` inherits this race safety automatically
- AES-256-GCM at-rest encryption for `HIGHLY_SENSITIVE` payloads, already proven for these exact schema shapes (§4)
- Tenant isolation via `(tenant_id, session_id)`, already directly attacked and confirmed at the `DocumentProcessor` level (HV-010)
- `EvidenceRequirement`/`ThresholdDefinition`/policy condition evaluation — evidence-type-agnostic, works identically once real MRZ/Barcode results exist
- `DOCUMENT_AUTHENTICITY` boundary already closed (DP-001 Decision 6) — MRZ check-digit success/failure is already forbidden from being conflated with authenticity, precedent inherited not reopened

---

## 6. Where MRZ and Barcode/QR should NOT be assumed identical

Per your explicit instruction. Five grounds, none of them spec text (the spec draws no distinction at all — §2), all of them either standards-grounded or directly traceable to language DP-001 already froze:

1. **Different technology class.** MRZ is fixed-format OCR of a standardized text zone (ICAO Doc 9303 TD1/TD2/TD3 — a defined character set, defined per-field lengths, a defined weighted-modulo-10 check-digit algorithm). Barcode/QR is a symbology-decode problem (Code128, PDF417, QR, possibly others) with no single universal payload schema — a PDF417 might encode AAMVA-formatted fields; a QR might encode an opaque URL, free text, or nothing identity-related at all.

2. **Check-digit validity has a defined algorithmic meaning for MRZ with no barcode analogue.** ICAO 9303's check-digit algorithm gives MRZ a standards-grounded notion of "structurally read correctly but the data says corrupted/tampered/misread" that barcode decoding doesn't share — by the time a barcode decode library reports a successful decode, symbol-level integrity (the barcode's own error-correction/CRC) has typically already been established internally, or the decode fails outright. Barcode's failure mode more naturally collapses into read-vs-not-read; MRZ's genuinely has a third state (read, but the data itself fails validation).

3. **Different absence semantics per the frozen V1 catalog.** DP-001 Decision 5 (frozen): *"`ICAO_PASSPORT_DATA_PAGE` MUST be modeled as an MRZ-bearing document and MUST therefore support the dedicated MRZ processing path."* MRZ absence on a passport data page is anomalous. Nothing in DP-001 or the spec establishes any of the three V1 catalog document types as barcode-bearing — `BARCODE_QR = NOT_SUBMITTED` is plausibly the *ordinary, expected* case for the entire current catalog, not a notable absence the way MRZ absence on a passport would be. See Decision 7.

4. **Sensitivity classification's own frozen caveat already reserves divergence.** DP-001 Decision 1 (frozen): *"any future per-symbology split of `BARCODE_QR` (e.g. an opaque-reference QR vs. a PDF417 encoding a full identity record), MUST be reassessed against this same payload-content test if their actual payload semantics change."* No equivalent reservation exists for MRZ, because MRZ payloads are, by ICAO 9303 design, always identity-bearing when present. See Decision 10.

5. **Different threat-model shape under SEC-7.22.5,** even though the requirement text is identical for both (§3) — an MRZ parser is an OCR-then-fixed-grammar-parse pipeline over a small standardized zone; a barcode/QR decoder is a symbology-detection-then-binary-payload-decode pipeline potentially handling multiple competing symbologies and arbitrary-length binary payloads. Deferred beyond this discovery (library selection is out of scope, §1) but worth naming now so it isn't lost.

---

## 7. Failure/reliability semantics — frozen mapping

Mirroring DP-001 §11's format. This table is now the frozen outcome of Decisions 1, 2, 3, 7, and 9 below — not a proposal.

| Scenario | Evidence-level outcome | Reason code | Reusable/retryable |
|---|---|---|---|
| MRZ zone not present / not detected | `MRZ = NOT_SUBMITTED` | — | Terminal/reusable |
| MRZ zone detected but unreadable / no usable text extracted | `MRZ = INCONCLUSIVE` | `MRZ_UNREADABLE` | Terminal/reusable |
| MRZ text extracted but not a valid ICAO 9303 TD1/TD2/TD3 structure | `MRZ = INCONCLUSIVE` | `MRZ_MALFORMED` | Terminal/reusable |
| MRZ structurally valid, one or more check digits fail | `MRZ = FAIL` | `MRZ_CHECK_DIGIT_MISMATCH` | Terminal/reusable |
| MRZ structurally valid, all check digits pass | `MRZ = PASS` | — | Terminal/reusable |
| MRZ parser capability unavailable | `MRZ = UNAVAILABLE` | `MODEL_UNAVAILABLE` | Retryable |
| Barcode/QR not present / not detected | `BARCODE_QR = NOT_SUBMITTED` | — | Terminal/reusable |
| Barcode/QR symbol detected but cannot decode | `BARCODE_QR = INCONCLUSIVE` | `BARCODE_UNREADABLE` | Terminal/reusable |
| Barcode/QR decodes at the symbol level, payload matches no recognized schema | `BARCODE_QR = INCONCLUSIVE` | `BARCODE_PAYLOAD_UNRECOGNIZED` | Terminal/reusable |
| Barcode/QR decodes into a recognized schema, payload fails validation against it | `BARCODE_QR = INCONCLUSIVE` | `BARCODE_PAYLOAD_MALFORMED` | Terminal/reusable |
| Barcode/QR decodes into a recognized, valid payload | `BARCODE_QR = PASS` | — | Terminal/reusable |
| Barcode/QR decoder capability unavailable | `BARCODE_QR = UNAVAILABLE` | `MODEL_UNAVAILABLE` | Retryable |
| Ambiguous capture (>1 DOCUMENT evidence) | `MRZ = INCONCLUSIVE` / `BARCODE_QR = INCONCLUSIVE` | `AMBIGUOUS_DOCUMENT_CAPTURE` | Terminal/reusable |
| Partial pipeline failure (MRZ fails, Barcode/QR succeeds, or vice versa) | Each stands independently (REL-10.15) | — | **[inherited, no new work]** |

**`BARCODE_QR` never resolves to `FAIL` in Phase 2** (Decision 2) — its outcome space is `NOT_SUBMITTED`/`INCONCLUSIVE`/`PASS`/`UNAVAILABLE` only, per the governing principle above: a decoder establishes successful-decode-or-not, never a negative finding about the document itself.

---

## 8. Recommended implementation shape

No change to DP-001's overall architecture diagram (§15 of DP-001) — this section only concretizes the two new leaves:

```
DocumentProcessor.process()
        │
        ├── _run_quality            (unchanged, Phase 1)
        ├── _run_classification     (unchanged, Phase 1)
        ├── _run_mrz                (NEW — same shape: existing-effective
        │                            check, ambiguous short-circuit,
        │                            capability call, CapabilityUnavailableError
        │                            catch, status mapping, persist, commit)
        └── _run_barcode            (NEW — same shape)
                │
                ▼
    MRZParser.parse(image) -> MRZExtraction | None
    BarcodeDecoder.decode(image) -> BarcodeExtraction | None
                │
                ▼
    EvidenceResultService.create()/supersede()   (existing, unmodified)
                │
                ▼
    Decision Engine   (existing, unmodified)
```

**Frozen (Decision 7):** `_run_mrz`/`_run_barcode` run unconditionally, mirroring Phase 1's unconditional quality/classification calls — no branching on the effective `DOCUMENT_CLASSIFICATION` result to skip either stage for document types not expected to carry an MRZ or barcode. `NOT_SUBMITTED` absorbs the "no zone/symbol found" case regardless of document type; any different evidentiary weight for "MRZ missing on a document type that should have one" is a policy-author's responsibility, not evidence-producer logic. No `DocumentType -> {has_mrz, has_barcode}` capability-flag mapping is built.

---

## 9. Frozen decisions

**Decision 1 — MRZ status vocabulary & malformed-vs-invalid semantics. FROZEN, AMENDED.**

> MRZ evidence MUST use the following status mapping, and no additional domain-specific status label (declining EVD-3.6's optional allowance):
>
> - No MRZ zone detected → `NOT_SUBMITTED`.
> - MRZ zone detected but unreadable / no usable text extracted → `INCONCLUSIVE`, reason code `MRZ_UNREADABLE`.
> - Text extracted but does not conform to a valid ICAO 9303 TD1/TD2/TD3 structure → `INCONCLUSIVE`, reason code `MRZ_MALFORMED`.
> - Structure valid, one or more check digits fail → `FAIL`, reason code `MRZ_CHECK_DIGIT_MISMATCH`.
> - Structure and all check digits valid → `PASS`.
> - Parser capability unavailable → `UNAVAILABLE`, reason code `MODEL_UNAVAILABLE`.
>
> Per the governing principle (top of this document): `FAIL` is reserved for a check that ran to completion and established a genuine negative result. Neither an unreadable MRZ zone nor a structurally malformed read has established anything negative about the document — both remain `INCONCLUSIVE`, distinguished from each other only by reason code, so operators can tell "couldn't see it" from "couldn't parse it" from "parsed it and the data is wrong."

Rejected: this document's own original draft, which proposed rejecting structurally malformed MRZ before persistence (mirroring DP-001's OCR-malformed-output handling, discarding it rather than recording it). That would have thrown away observable evidence of a real processing outcome and collapsed two genuinely different signals — a garbled read and a well-formed-but-corrupted read — into the same silence.

**Decision 2 — Barcode/QR status vocabulary & malformed-payload semantics. FROZEN, AMENDED.**

> Barcode/QR evidence MUST use the following status mapping:
>
> - No supported barcode/QR detected → `NOT_SUBMITTED`.
> - Symbol detected but cannot decode → `INCONCLUSIVE`, reason code `BARCODE_UNREADABLE`.
> - Decodes successfully at the symbol level but the payload matches no recognized schema → `INCONCLUSIVE`, reason code `BARCODE_PAYLOAD_UNRECOGNIZED`.
> - Decodes into a recognized payload schema but that payload is malformed/invalid against it → `INCONCLUSIVE`, reason code `BARCODE_PAYLOAD_MALFORMED`.
> - Decodes into a recognized, valid payload → `PASS`.
> - Decoder capability unavailable → `UNAVAILABLE`, reason code `MODEL_UNAVAILABLE`.
>
> **`BARCODE_QR` MUST NOT emit `FAIL` in Phase 2.** A barcode decoder establishes only whether it did or did not successfully decode a recognized, valid payload — it does not establish a negative finding about the underlying document (a QR code carrying an unexpected but well-formed URL is not itself evidence the document is invalid). `FAIL` remains reserved for a future phase that defines an actual barcode-domain negative condition, should one be identified.

This resolves the one place the original draft had no confident recommendation (recognized-symbol-but-unrecognized-payload) by applying the governing principle rather than picking between the two candidates arbitrarily: neither "unrecognized payload" nor "recognized-but-invalid payload" is a positive establishment of a negative condition, so both stay `INCONCLUSIVE`, distinguished by reason code exactly as MRZ's two malformation states are.

**Decision 3 — Reason codes for MRZ/Barcode failure modes. FROZEN, EXPANDED.**

> Extends `DocumentReasonCode` (`core/document/reason_codes.py`) with: `MRZ_UNREADABLE`, `MRZ_MALFORMED`, `MRZ_CHECK_DIGIT_MISMATCH`, `BARCODE_UNREADABLE`, `BARCODE_PAYLOAD_UNRECOGNIZED`, `BARCODE_PAYLOAD_MALFORMED`. Reuses `MODEL_UNAVAILABLE` and `AMBIGUOUS_DOCUMENT_CAPTURE` unchanged for their existing meanings.
>
> This remains sited under DP-001's still-open Open Question 3 (where evidence-level reason codes ultimately belong in code) — extending the Phase-1-established interim home (`core/document/reason_codes.py`), not resolving that question.

Six codes rather than the original draft's three: the expanded Decision 1/2 status mappings need a distinct code per distinguishable failure mode (`couldn't see it` / `couldn't parse it` / `parsed it but it's wrong`, on both sides) for the reliability-architecture observability this project's own discipline requires — collapsing them back to fewer codes would re-erase the distinction Decisions 1–2 exist to preserve.

**Decision 4 — Confidence/quality scoring. FROZEN, as proposed.**

> No confidence or quality field is added to `MrzResult`/`BarcodeQrResult`/`MRZExtraction`/`BarcodeExtraction` in Phase 2. Deferred until a real (non-deterministic) adapter exists with an actual confidence signal to report — a populated-but-meaningless placeholder would violate EVD-3.13's documented-semantics requirement the moment it's set.

**Decision 5 — MRZ result schema shape. FROZEN, as proposed.**

> `MrzResult`/`MRZExtraction` keep exactly `raw: str, fields: dict[str, str]`. No ICAO 9303 field breakdown is added at this layer — DP-001 Decision 7 already reserves the canonical, addressable field breakdown for `DOCUMENT_FIELD_EXTRACTION`; `MRZ` stays a source-specific, non-canonical extraction representation. The parser's internal ICAO 9303 field understanding (document code, issuing state, document number, nationality, DOB, sex, expiry, optional data, check digits) MAY inform what keys populate `fields`, but `fields` carries no schema-level contract on which keys are guaranteed present.

**Decision 6 — Barcode/QR result schema shape. FROZEN, AMENDED.**

> `BarcodeQrResult` AND `BarcodeExtraction` both gain `symbology: str | None` — the field MUST exist at both the EvidenceResult-schema layer and the domain-type layer, not the schema alone, since `DocumentProcessor` has no other authoritative source to persist it from. `symbology` is populated with normalized producer-chosen values (e.g. `QR_CODE`, `PDF417`, `CODE128`, `AZTEC`, `DATA_MATRIX`) and is NOT policy-addressable in Phase 2 (the same nested-field limitation already governing `fields`, DEC-5.14). This decision reserves the field only — the actual supported symbology set is constrained later, once a real decoder library is selected. `raw`/`fields` stay unchanged, per Decision 5's reasoning.

**Decision 7 — Absence semantics & orchestration invocation. FROZEN.**

> `MRZ = NOT_SUBMITTED` and `BARCODE_QR = NOT_SUBMITTED` are evidence-level facts only. `DocumentProcessor` MUST NOT treat MRZ absence on `ICAO_PASSPORT_DATA_PAGE` differently from MRZ absence on any other V1 catalog document type at the evidence-production layer — any different evidentiary weight for "MRZ missing on a document type that should have one" belongs to policy, not the evidence producer, per the same reasoning EVD-3.25 applies to conflict interpretation.
>
> `_run_mrz`/`_run_barcode` MUST be invoked unconditionally from `DocumentProcessor.process()`, identically to `_run_quality`/`_run_classification` — no branching on the effective `DOCUMENT_CLASSIFICATION` result to skip either stage for document types not expected to carry an MRZ or barcode. A `DocumentType -> {has_mrz, has_barcode}` capability-flag mapping is explicitly NOT built in Phase 2; a policy author can already express "this document type should have an MRZ" by conditioning on `DOCUMENT_CLASSIFICATION.result.document_type` alongside `MRZ.status`.
>
> `NOT_SUBMITTED` on `MRZ`/`BARCODE_QR` MUST be documented, in the capability port docstrings, as meaning the capability found no applicable/readable signal within the submitted capture — it does NOT mean the verification session or the document capture itself was never submitted. This removes the ambiguity of reusing one status name for two different absence concepts (EVD-3.7's own `NOT_SUBMITTED` example is capture-level; this is zone/feature-level within an already-submitted capture).

**Decision 8 — Deterministic implementation shape for Phase 2. FROZEN, as proposed.**

> MRZ's deterministic Phase 2 implementation MUST split into (a) a stand-in zone-detection/text-extraction step, mirroring Phase 1's non-representative-stub pattern (e.g. fixed test-marker-driven), and (b) a real, standards-conformant ICAO 9303 check-digit validator. The check-digit validator MUST NOT be faked — writing it correctly costs no more than writing a stand-in, and a fake check-digit validator would misrepresent what Phase 2 actually proves.
>
> Barcode/QR's deterministic Phase 2 implementation MUST be a full stand-in (no real symbology-decode logic), mirroring `DeterministicDocumentClassifier`'s pattern exactly — real decoding is deferred to a future real-adapter phase, the same treatment DP-001 already gave OCR.
>
> The implementation plan following this discovery MUST describe `DeterministicMRZParser`'s check-digit logic as real, not as a deterministic stand-in, so as not to mischaracterize what Phase 2's tests actually establish.

This is the one place Phase 2 could not simply copy Phase 1's "deterministic = stand-in" pattern: ICAO 9303's check-digit algorithm is a fully-specified, deterministic, correct-or-not computation with no "fake" version that differs from the "real" version the way a byte-length threshold differs from an actual blur-detection model.

**Decision 9 — Reusable-vs-retryable matrix extension. FROZEN, as proposed.**

> Phase 1's `_is_reusable()` matrix (`PASS`/`FAIL`/`INCONCLUSIVE` terminal and reusable; `UNAVAILABLE` retryable) extends unchanged to `NOT_SUBMITTED` (terminal/reusable) for MRZ/Barcode-QR — an absent MRZ/barcode zone on one attempt will not appear on a later attempt without a new capture, so re-invoking the capability against the same bytes cannot produce a different answer. This is confirmed as the intended answer, not merely the accidental output of the current binary `status is not UNAVAILABLE` check, which needs no code change to already produce it.
>
> This is a Phase-2-scoped processing rule, not DP-001's broader still-open general retryable-with-a-budget matrix (§14 Open Question 8), which remains open beyond this narrow confirmation.

**Decision 10 — Sensitivity classification reassessment. FROZEN — no change.**

> `MRZ` and `BARCODE_QR` remain `HIGHLY_SENSITIVE`, unchanged from DP-001 Decision 1. That decision's own per-symbology-split reservation is not triggered by anything in this document — Decision 6 declines to build payload-content-type detection, so no payload-semantics signal exists yet that would justify splitting `BARCODE_QR`'s classification. Raw barcode content remains encrypted even where a future barcode happens to contain only an opaque reference/URL; no payload-dependent classification machinery is built in Phase 2. Revisit only if and when a future phase actually distinguishes barcode payload types.

**Decision 11 — `DOCUMENT_FIELD_EXTRACTION` reconciliation excluded from DP-003. FROZEN.**

> The `DOCUMENT_FIELD_EXTRACTION` reconciliation *algorithm* (as distinct from DP-001 Decision 7's already-frozen schema) is explicitly out of scope for Phase 2. It is deferred to a dedicated future discovery once OCR exists and a genuine three-source (OCR + MRZ + Barcode/QR) reconciliation can be designed honestly — designing it now against only two sources risks a redesign the moment OCR lands. This narrows DP-001's own original (pre-this-session) phase plan, which bundled OCR + MRZ + Barcode + field-reconciliation into one phase; that bundling is superseded by this decision.

---

## 10. Proposed implementation phases

**Phase 2a — `MRZParser`/`BarcodeDecoder` interfaces already exist; add `_run_mrz`/`_run_barcode` to `DocumentProcessor`**, wired identically to Phase 1's stages (§8), plus the schema change from Decision 6 (`symbology` field) and the reason-code additions from Decision 3.

**Phase 2b — Deterministic implementations** per Decision 8's split: a stand-in MRZ zone-detector/OCR feeding a real ICAO 9303 check-digit validator; a full stand-in barcode decoder.

**Phase 2c — Hostile validation (HV-011)**, following the exact HV-010 discipline: tenant isolation, concurrent-race attack (the same class of bug HV-010 found should be checked again here even though the underlying `EvidenceResultService.create()` fix is now generic — worth re-confirming it holds for these two new call sites specifically, not assumed), malformed-input attacks specific to each capability (crafted MRZ text, malformed barcode payloads per SEC-7.21), encryption-at-rest re-confirmation once real (non-canary) MRZ/Barcode content exists, and the unexpected-exception-propagation test pattern extended to `MRZParser`/`BarcodeDecoder`.

Not proposing further phase breakdown here — this level of detail belongs in DP-004, the companion implementation plan (mirroring DP-002's role for Phase 1), which locks the concrete engineering shape (exact schema/domain-type diffs, `_run_mrz`/`_run_barcode` control flow, producer/provenance constants, test plan, HV-011 attack surface, explicit non-goals) from these 11 now-frozen decisions. Implementation does not begin until DP-004 is itself drafted and reconciled, per the DP-001 → DP-002 precedent.

---

## 11. Conformance/test strategy

Same layering DP-001 §18 already established, restated for this phase's specific new surface:
- `tests/unit/` — MRZ check-digit algorithm correctness (real, per Decision 8 — this deserves thorough positive/negative/edge-case unit coverage precisely because it's real logic, not a stand-in), deterministic stand-in behavior for zone-detection and barcode decoding.
- `tests/integration/` — real-Postgres `EvidenceResultService.create()` round-trips for `MRZ`/`BARCODE_QR` with real-shaped payloads (not placeholder canaries), full orchestration tests mirroring `test_document_processor.py`'s existing pattern, extended to the two new stages.
- `tests/contracts/security/` — SEC-7.21/SEC-7.22 adversarial-input tests once a real library is chosen (out of this discovery's scope, but the contract this phase's schema/status decisions must support).
- HV-011, once Phase 2 lands, per §10.

---

## Appendix — raw discovery source

The full requirement-by-requirement spec trace and the full repository inventory (exact Protocol signatures, dataclass/schema fields, enum values, classification mappings, and the complete whole-repo grep sweep) that this document synthesizes are available in this session's transcript and can be re-expanded on request — not reproduced in full here, per the same navigability rationale DP-001's own appendix states.
