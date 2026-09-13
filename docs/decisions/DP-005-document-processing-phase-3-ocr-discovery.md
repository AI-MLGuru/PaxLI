# DP-005 — Document Processing Phase 3 Discovery (OCR)

**Status:** RECONCILIATION COMPLETE — all 12 decisions frozen (§10). No production code has been changed during discovery or reconciliation. Implementation is NOT yet authorized: per the DP-001 → DP-002 / DP-003 → DP-004 precedent, a companion implementation plan (DP-006) locks the concrete engineering shape from these frozen decisions before any code is written.
**Scope:** OCR (`OCREngine`/`OCR_EXTRACTION`) as the third document-processing capability. Cross-source field reconciliation (`DOCUMENT_FIELD_EXTRACTION`, consuming OCR + MRZ + Barcode/QR) is explicitly OUT of this phase, per Decision 0/11 — it is a distinct architectural problem ("what text can I extract" vs. "given independently produced evidence from three sources, what canonical fields can we derive, and what do we do when sources disagree") and gets its own dedicated discovery once Phase 3 is closed. The title was corrected during reconciliation to drop "& Reconciliation" for exactly this reason — Phase 3's name, scope, decisions, and implementation boundary now stay aligned.
**Method:** full trace of `docs/specification/` for every OCR- and reconciliation-relevant requirement, plus a full repository inventory of everything Phase 1/2 already put in place that OCR either inherits or must be brought into line with. Citations below are `file:line` where available.
**Precedent:** DP-001's 7 frozen decisions and DP-003's 11 frozen decisions are binding architecture this document does not relitigate except where explicitly noted (notably: DP-001 §11's OCR malformed-output proposal was never itself frozen — see §4).

### Governing principle established during reconciliation

> **A capability's `VALID`/success outcome asserts only that the capability satisfied its own output contract. It never asserts correctness, authenticity, identity validity, or semantic correctness of the content.**

For OCR specifically: `OCR_EXTRACTION = VALID` means the OCR capability successfully produced an extraction satisfying its defined extraction contract — nothing more. It does not mean the document is authentic, the identity is verified, the extracted fields are correct, or the document is untampered. Each layer of the pipeline gets progressively more semantic without an earlier layer impersonating a later one:

```
        OCR                              "Can I extract text?"
         │                          ┌───────────┴───────────┐
         ▼                          VALID                UNREADABLE
   OCR evidence
         │
         ▼
  Field extraction (Phase 4)
         │
         ▼
   Reconciliation (Phase 4)
         │
         ▼
   Decision Engine
```

This governing principle is stated once here because it is the frozen basis for Decision 2 and disciplines every later phase that consumes `OCR_EXTRACTION` — reconciliation, policy, and the Decision Engine must not treat a `VALID` OCR read as anything beyond "text was recognized."

## Reconciliation log

| # | Decision | Status |
|---|---|---|
| 0 | Phase 3 scope | **FROZEN — Option A: OCR only** |
| 1 | `OCREngine` capability-contract redesign (outcome wrapper) | **FROZEN** |
| 2 | OCR status vocabulary & outcome space | **FROZEN — `UNREADABLE` + `VALID` only** |
| 3 | OCR absence semantics | **FROZEN — non-Optional, no `NOT_SUBMITTED`** |
| 4 | Malformed-output handling | **FROZEN — DP-003's pattern supersedes DP-001 §11** |
| 5 | Reason codes | **FROZEN — `OCR_UNREADABLE` + existing generic codes only** |
| 6 | Confidence/quality scoring | **FROZEN — none for the deterministic implementation** |
| 7 | `OcrExtractionResult` schema shape | **FROZEN — `raw` + `fields`** |
| 8 | Deterministic implementation shape | **FROZEN — full marker-driven stand-in** |
| 9 | Reusable-vs-retryable matrix extension | **FROZEN — direct extension** |
| 10 | Sensitivity classification reassessment | **FROZEN — no change** |
| 11 | Reconciliation architecture | **FROZEN — deferred to Phase 4; only the conflict-authority constraint carries forward** |

---

## 1. Scope

In scope: everything needed to take a classified `DOCUMENT` capture through OCR into a real `OCR_EXTRACTION` `EvidenceResult`, without reopening DP-001/DP-003's frozen architecture. `DOCUMENT_FIELD_EXTRACTION`'s canonical schema implementation and its reconciliation algorithm are explicitly OUT of scope (Decision 0, frozen as Option A) — both are deferred together to a dedicated Phase 4 discovery.

Out of scope regardless of Decision 0's outcome:
- `DOCUMENT_AUTHENTICITY` — DP-001 Decision 6 (frozen) still forecloses this for the whole vertical slice.
- `IDENTITY_CONSISTENCY` — DP-001's Open Question 5 (what it actually checks) remains untouched by this research; still open, still a future phase's problem.
- Real OCR library selection/integration — this discovery produces the semantic contract; it does not choose a Tesseract/PaddleOCR/cloud-OCR adapter.

---

## 2. The headline finding — OCR gets more spec mentions than MRZ/Barcode, but no more defined semantics

DP-003's headline finding was that MRZ/Barcode get exactly one substantive spec hit. OCR is measurably richer in *mentions* — 6 hits instead of 1, including two MRZ/Barcode never got:

- **A spec-blessed reason code.** EVD-3.14's example catalog names `OCR_UNREADABLE` explicitly (`part-03-evidence-semantics.md:261`). MRZ and Barcode got zero named codes anywhere — DP-003 had to coin all six of theirs from nothing but the governing principle. OCR inherits one for free.
- **The spec's only lineage example.** EVD-3.17's canonical pipeline illustration is *"capture to quality to OCR to identity consistency"* (`part-03:298`) — OCR by name, not MRZ, not Barcode, not `DOCUMENT_FIELD_EXTRACTION`.

**Neither changes the practical conclusion.** EVD-3.5.2 ("evidence types MUST have defined semantics before being accepted by the Decision Engine") is exactly as unsatisfied for OCR as DP-003 found for MRZ/Barcode — no section anywhere defines OCR's status vocabulary, schema shape, or failure taxonomy. The extra mentions are illustrative examples, not specifications. DP-005 still has to build OCR's semantics from the same generic anchors (EVD-3.6/3.7/3.24, REL-10.21, the DP-003 governing principle) DP-003 used for MRZ/Barcode — just with slightly richer raw material (one blessed reason code, one lineage citation) to start from.

**"Reconciliation" and "cross-source"/"cross-check" return zero hits anywhere in the specification.** Whatever DP-005 designs for reconciliation is pure PaxLI-originated architecture, grounded only in the generic conflict-authority requirements (§5 below) and DP-001 Decision 7's already-frozen schema.

---

## 3. Two load-bearing repository findings

**Finding 1 — `OCREngine` is still the pre-redesign shape.** Unlike `MRZParser`/`BarcodeDecoder` (redesigned during DP-004 §3's reconciliation into an explicit outcome-wrapper pattern), `OCREngine` has not been touched since Phase 1:

```python
class OCREngine(ABC):
    """No Phase 1 implementation -- interface only (DP-001 Decision 3)."""

    @abstractmethod
    async def extract(self, image: bytes) -> OCRExtraction:
        raise NotImplementedError
```

Bare, non-`Optional`, no outcome enum. By `core/document/capabilities.py`'s own module-docstring rule — *"Where a capability port has an `Optional` return type, `None` means that the capability found no applicable input/presence to process... Capabilities whose domain necessarily applies to every submitted capture... need not use an optional return"* — OCR's correct shape depends on Decision 3 below (does "no applicable input" ever apply to OCR, or does OCR's domain necessarily apply to every capture the way Quality/Classification's does?). Either way, `OCREngine`/`OCRExtraction` need deliberate attention, not silent inheritance of whichever shape happens to already exist.

`core/document/types.py`'s current `OCRExtraction` is also fields-only, with no `raw` field:
```python
@dataclass(frozen=True)
class OCRExtraction:
    """Raw, per-source, non-canonical -- DP-001 Decision 7 keeps this
    shape unchanged; only DOCUMENT_FIELD_EXTRACTION (Phase 2) gets the
    hybrid canonical schema. No Phase 1 producer exists for this type."""
    fields: dict[str, str]
```
`core/evidence_result/schemas.py`'s `OcrExtractionResult` matches: `{fields: dict[str, str]}`, no `raw`. This is a real asymmetry against `MrzResult`/`BarcodeQrResult`, both of which carry `raw: str` — OCR currently has no natural place to persist the full extracted text, only an already-parsed-into-a-dict shape. See Decision 7.

**Finding 2 — `DOCUMENT_FIELD_EXTRACTION`'s canonical schema (DP-001 Decision 7, frozen since Phase 0) has never been implemented in code.** `DocumentFieldExtractionResult` today is still the placeholder shape:
```python
class DocumentFieldExtractionResult(BaseModel):
    fields: dict[str, str]
```
— identical to `OcrExtractionResult`, not the eight-canonical-field-plus-`extensions` hybrid schema Decision 7 specifies. This means the "reconciliation unlocks direct policy field-addressability" benefit (§8 below) is **not automatic** the moment reconciliation ships — it requires someone to actually build the Decision-7 Pydantic model. Nothing in DP-002/DP-003/DP-004 did this; it remains exactly as DP-001 left it.

Also confirmed: `parent_evidence_result_ids` — the field DP-001 Decision 2 designed specifically for stages like reconciliation that consume multiple upstream `EvidenceResult`s — is fully built, tenant/session-safety-tested at the service/repository layer, and has **zero real callers anywhere in the codebase**. `_run_quality`/`_run_classification`/`_run_mrz`/`_run_barcode` all only ever pass `source_reference`. A `DOCUMENT_FIELD_EXTRACTION` stage would be this field's first real use — confirming it was deliberate forward-declared scaffolding, not dead code, but also confirming nothing has exercised it in anger yet.

---

## 4. The DP-001-vs-DP-003 tension on malformed output

DP-001 §11's original (never frozen — its own closing line says *"these are proposed mappings for reconciliation, not frozen decisions"*) failure-mapping table proposed: *"OCR executes, produces malformed/unparseable output → Rejected at `create()` by `validate_result_payload()`... never persisted as a trusted result."* This mirrors how DP-003's own first draft handled MRZ before reconciliation corrected it.

DP-003's reconciliation explicitly rejected that pattern for MRZ (§ Decision 1, frozen): malformed MRZ is persisted as `INCONCLUSIVE` with a distinguishing reason code, not silently discarded — because discarding throws away observable evidence of a real processing outcome and collapses "couldn't read it" into the same silence as "couldn't parse it."

**REL-10.21.1's exact text favors DP-003's pattern textually**: *"Inference failure MUST be represented as processing failure **or inconclusive evidence as applicable**."* The spec itself names "inconclusive evidence" as an available representation — DP-001's original "reject before persistence" reading doesn't use this option at all. Recommend DP-005 explicitly supersede DP-001 §11's stale OCR row and apply DP-003's governing principle to OCR from the start, for consistency across all three extraction capabilities. Since DP-001 §11 was never frozen, this isn't reopening a decision — it's finishing one that was left provisional.

---

## 5. EVD-3.25 and the reconciliation-architecture question

Full text (`part-03-evidence-semantics.md:393-404`):

> Evidence may disagree, such as `FaceMatch = PASS` with `IdentityConsistency = FAIL`. Conflicts MUST NOT be resolved through implicit precedence. Conflict semantics belong to the Decision Engine and applicable policy.
>
> - **EVD-3.25.1** Conflicting evidence MUST remain individually observable.
> - **EVD-3.25.2** A component MUST NOT silently overwrite contradictory evidence.
> - **EVD-3.25.3** Conflict resolution MUST be defined by Decision Engine policy.
> - **EVD-3.25.4** Unresolvable conflicts MUST produce a safe non-verifying decision such as `INCONCLUSIVE`.

Its twin at decision time, DEC-5.22 (`part-05-decision-engine.md:344-354`), and the constitutional version, Invariant 02 §2.5 (`part-02-architectural-invariants.md:139`: *"Unresolved conflicting evidence MUST result in `INCONCLUSIVE`"*), say the same thing at two other layers.

**The spec's own worked examples are cross-*domain* (`FaceMatch` vs. `IdentityConsistency`), never same-field cross-*source* (`OCR.surname` vs. `MRZ.surname`).** This is a genuine interpretive gap, not a defined answer — but the architecture EVD-3.25.1/3.25.2 point toward is fairly specific: raw per-source evidence must stay separately observable (already structurally guaranteed — `OCR_EXTRACTION`/`MRZ`/`BARCODE_QR` are independent immutable rows regardless of what reconciliation does), and a component (here, `DocumentProcessor`'s reconciliation stage) must not *silently overwrite* contradictory evidence with a guessed winner. Combined with EVD-3.25.3/DEC-5.22.3 assigning conflict-*resolution* authority to policy/Decision Engine, not the evidence producer, the textually-supported design is:

> `DOCUMENT_FIELD_EXTRACTION`'s reconciliation logic should perform deterministic **normalization** (case-folding, whitespace/diacritic handling — the "same normalization pass" DP-001 Decision 7 already requires for `full_name`/`surname`/`given_names` consistency), but should stop short of **adjudicating** which source is correct when sources still disagree after normalization. A genuine post-normalization disagreement should surface as an `INCONCLUSIVE`-shaped, reason-coded `DOCUMENT_FIELD_EXTRACTION` result — leaving actual adjudication to policy, per EVD-3.25.3/DEC-5.22.3's explicit assignment of that authority.

This full normalization-then-surface design is presented as spec-grounded input for Phase 4's own discovery to weigh — Decision 11 (§10) freezes only the narrower, already-established constraint beneath it (no implicit-precedence adjudication), not this complete design.

---

## 6. What's normatively/architecturally different about OCR vs. MRZ/Barcode

Per the established discipline (don't assume sibling capabilities are identical), five grounds — none from spec text (which draws no distinction), all standards/engineering-grounded exactly as DP-003's own five points were for MRZ vs. Barcode:

1. **Broadest, least-constrained technology class of the three.** MRZ is fixed-zone, fixed-grammar. Barcode is fixed-symbology decode. OCR is unconstrained free-text recognition over an entire document image.
2. **No standards-defined negative condition at all** — not even Barcode's symbol-level decode-success/failure. OCR's recognition is inherently graded/probabilistic with no crisp validity concept, arguing for an outcome space at least as narrow as Barcode's (no `FAIL`), for a different underlying reason.
3. **Categorically larger output-side adversarial surface.** MRZ's closed ICAO alphabet and Barcode's schema-constrained payloads are narrow; OCR's recognized text is unconstrained and could contain anything — directly engaging SEC-7.21's *"unexpected Unicode"* adversarial-input category (`part-07-security-and-governance.md:338`) in a way neither Phase 2 capability had to confront.
4. **Genuinely novel absence semantics.** MRZ/Barcode have a real "zone/symbol not physically present" concept. OCR conventionally runs over the whole document and almost always produces *something* — what "no usable signal at all" means for a whole-image recognition task has no precedent in either prior phase. See Decision 3.
5. **More concretely live `PRV-11.7.6` (temporary processing copies) exposure.** OCR pipelines (deskew/crop/binarize/upscale preprocessing, or shelling out to an external engine) are more likely to write intermediate temp files than MRZ/Barcode's narrower crop-then-decode preprocessing. Still a library-selection-time question, out of this discovery's scope, but flagged with more urgency than DP-003 could for MRZ/Barcode.

---

## 7. Failure/reliability semantics — frozen mapping

Now the frozen outcome of Decisions 2, 3, 5, and 9 below — not a proposal.

| Scenario | Evidence-level outcome | Reason code | Notes |
|---|---|---|---|
| OCR attempted, no usable text recognized at all | `INCONCLUSIVE` | `OCR_UNREADABLE` (spec-blessed) | The one reason code inherited directly from EVD-3.14, not coined |
| OCR attempted, text recognized | `VALID` | — | No validity concept exists for OCR to fail against on its own — see §6 point 2. No `PASS`/`FAIL` vocabulary here — Decision 2 uses `OCRReadOutcome.VALID`, distinct domain vocabulary from `EvidenceResultStatus`; `DocumentProcessor` maps `VALID` to `EvidenceResultStatus.PASS` when persisting |
| OCR capability unavailable | `UNAVAILABLE` | `MODEL_UNAVAILABLE` (reused) | Standard `CapabilityUnavailableError` path |
| Ambiguous capture (>1 `DOCUMENT` evidence) | `INCONCLUSIVE` | `AMBIGUOUS_DOCUMENT_CAPTURE` (reused) | Already-built precondition, shared with every other stage |

**No "document not classified / not attempted" row exists** — per Decision 3 (frozen), OCR has no `NOT_SUBMITTED` outcome and is invoked unconditionally regardless of upstream quality/classification results.

**No `FAIL`, no `MALFORMED` state proposed for OCR** — unlike MRZ, there is no structural-grammar check to fail; unlike both MRZ and Barcode, there is no algorithmic validity check at all. This makes OCR's outcome space narrower than either Phase 2 capability's, for reasons specific to OCR (§6 point 2), not a mechanical copy of Barcode's table.

---

## 8. Recommended implementation shape

```
DocumentProcessor.process()
        │
        ├── _run_quality            (unchanged)
        ├── _run_classification     (unchanged)
        ├── _run_mrz                (unchanged, Phase 2)
        ├── _run_barcode            (unchanged, Phase 2)
        └── _run_ocr                (NEW — same shape: existing-effective
                                      check, ambiguous short-circuit,
                                      capability call, CapabilityUnavailableError
                                      catch, outcome-map lookup, persist, commit)
                │
                ▼
    OCREngine.extract(image) -> OCRReadResult (non-Optional -- Decision 3)
                │
                ▼
    EvidenceResultService.create()/supersede()   (existing, unmodified)
```

`_run_ocr` is the last stage `process()` runs in Phase 3 — no `_run_field_extraction` stage exists yet. Per Decision 0/11, that stage (and the first real use anywhere in the codebase of `parent_evidence_result_ids`, reading the effective `OCR_EXTRACTION`/`MRZ`/`BARCODE_QR` results directly rather than via a capability call) is Phase 4's to design and build, not Phase 3's.

---

## 9. The central scope question — FROZEN as Option A

Three options were evaluated (full comparative reasoning preserved below for the record). **Option A is frozen: Phase 3 = OCR only.**

```
Phase 3 (this document): OCR_EXTRACTION
Phase 4 (future discovery, dedicated): DOCUMENT_FIELD_EXTRACTION schema + reconciliation algorithm, together
```

**Rationale for the freeze, boundary integrity is the load-bearing reason, not merely schema-timing convenience:** OCR and reconciliation answer two different architectural questions. OCR answers *"what text can I extract from this document image?"* — a question about one capability's own recognition contract. Reconciliation answers *"given independently produced evidence from OCR, MRZ, and Barcode, what canonical document fields can we derive, and what do we do when those sources disagree?"* — a question about cross-source adjudication, normalization, provenance, and policy interaction that has nothing to do with OCR's own semantics. Combining them in one phase would mean HV-012 has to simultaneously attack OCR recognition semantics, field normalization, source disagreement, provenance, conflict representation, policy interaction, and supersession/rerun behavior — too much surface for one hostile-validation cycle to reason about cleanly, breaking the exact discipline that made Phase 2's HV-011 pass legible and its findings (or lack thereof) trustworthy.

Options B (OCR + full reconciliation in one phase) and C (OCR + schema now, algorithm later) were both considered and rejected — B for the surface-size reason above, C because it ships a `DocumentFieldExtractionResult` schema nothing in Phase 3 would populate (no stage calls `create()` for that type until the reconciliation algorithm exists), making it functionally indistinguishable from Option A plus one inert file.

**Reconciliation's open-question set is preserved verbatim below, carried forward in full to Phase 4's own dedicated discovery — none of it is answered by this document, per Decision 11:**

- Which source wins when values disagree, if any — or does disagreement never get "won," only surfaced? (EVD-3.25's conflict-authority language, §5, bears on this, but the answer is deliberately not pre-decided here — see Decision 11.)
- What constitutes a conflict, precisely — exact-match required post-normalization, or some tolerance (e.g., transliteration variants of the same name)?
- Is absence different from contradiction — one source silent on a field vs. two sources actively disagreeing?
- Does OCR confidence participate in reconciliation, once a real (non-deterministic) OCR adapter eventually has one? (Deterministic Phase 3 has no confidence field per Decision 6, so this is moot until then.)
- Does MRZ's check-digit validity grant it precedence over OCR for the same field, or does EVD-3.25.1's "must remain individually observable" argue against any built-in precedence at all?
- Can barcode data override OCR, or vice versa?
- What happens when only one source provides a field (e.g., Barcode absent per Decision 3's frozen absence semantics, only OCR+MRZ contribute)?
- Are source-specific fields allowed into `extensions`, and under what rule?
- Can reconciliation itself produce `FAIL`, or only `PASS`/`INCONCLUSIVE` (mirroring the "no negative condition to establish" reasoning §6/§7 apply to OCR)?
- What provenance must be retained — is `parent_evidence_result_ids` sufficient, or does the reconciled result need to record *which* source contributed *which* field?
- How are upstream result IDs attached when one upstream result gets superseded after reconciliation already ran?
- Should reconciliation rerun automatically when an upstream source is superseded, and if so, does that supersede the reconciliation result too?
- What exactly does the Decision Engine consume — the reconciled `DOCUMENT_FIELD_EXTRACTION` row alone, or does policy retain the ability to condition on the raw per-source rows directly even after reconciliation exists?

**None of these are pre-answered by DP-005**, including questions that might look tempting to resolve by analogy — e.g., MRZ having a stronger structural-validity check (a real check-digit algorithm) than OCR does not by itself establish that MRZ should win a field-level disagreement; treating "has stronger internal validation" as "therefore takes precedence" is exactly the kind of implicit-precedence resolution EVD-3.25.1 warns against, and deciding it here — even by seemingly reasonable analogy — would be resolving it casually rather than through Phase 4's own dedicated discovery.

---

## 10. Frozen decisions

**Decision 0 — Phase 3 scope. FROZEN.**

> Phase 3 implements `OCR_EXTRACTION` only (Option A, §9). `DOCUMENT_FIELD_EXTRACTION`'s schema and reconciliation algorithm are explicitly out of scope and are deferred, together, to a dedicated Phase 4 discovery — not built separately, and not begun in this phase in any form.

**Decision 1 — `OCREngine` capability-contract redesign. FROZEN.**

> `OCREngine` is brought in line with DP-004 §3's outcome-wrapper pattern:
> ```python
> class OCRReadOutcome(StrEnum):
>     UNREADABLE = "UNREADABLE"
>     VALID = "VALID"
>     # No FAIL/MALFORMED members -- Decision 2.
>
> @dataclass(frozen=True)
> class OCRReadResult:
>     outcome: OCRReadOutcome
>     extraction: OCRExtraction | None   # None exactly when outcome=UNREADABLE
>
> class OCREngine(ABC):
>     async def extract(self, image: bytes) -> OCRReadResult:   # non-Optional -- Decision 3
>         raise NotImplementedError
> ```
> `extract()`'s return is **not** `Optional` — this is Phase 3's one deliberate structural departure from Phase 2's `MRZParser`/`BarcodeDecoder` pattern, per Decision 3's reasoning below, not an oversight.

**Decision 2 — OCR outcome/status vocabulary. FROZEN.**

> `OCR_EXTRACTION` uses exactly two outcomes: `UNREADABLE` and `VALID`. No `MALFORMED` (OCR has no structural grammar to violate the way MRZ's TD3 format does), no `CHECK_DIGIT_MISMATCH`-equivalent (no validity algorithm exists for OCR the way ICAO 9303 check digits exist for MRZ), no `FAIL` at all (per the governing principle above and §6 point 2: OCR never establishes a negative condition on its own). This is narrower than both Phase 2 capabilities' outcome spaces, for reasons specific to OCR's technology class, not a mechanical inheritance of either.
>
> `VALID` means exactly what the governing principle (top of this document) states: the OCR capability successfully produced an extraction satisfying its own output contract. It asserts nothing about document authenticity, identity verification, field correctness, or document integrity — those are later-layer concerns (Phase 4 reconciliation, policy, the Decision Engine) that MUST NOT be inferred from an `OCR_EXTRACTION = VALID` row in isolation.

**Decision 3 — OCR absence semantics. FROZEN.**

> `OCREngine.extract()` is non-Optional (Decision 1) and MUST be invoked unconditionally on every classified `DOCUMENT` capture — no `DocumentType`/upstream-result branching inside `DocumentProcessor` decides whether OCR runs, matching DP-003 Decision 7's precedent exactly. `OCR_EXTRACTION` has no `NOT_SUBMITTED` outcome.
>
> The governing reason is semantic, not merely precedential: `NOT_SUBMITTED` means the capability had nothing applicable to process — true for MRZ (a document either has an MRZ zone or it doesn't) and Barcode (a symbol is either printed or it isn't), false for OCR. A document image is inherently an OCR input. Even a blurred, low-contrast, handwritten, or otherwise unreadable image is still something OCR was applicable to and attempted — OCR was asked *"is there recognizable text in this image?"* and answered, even if the answer is no. That answer is a processing **outcome** (`UNREADABLE`), not an absence of applicability. Upstream quality or classification results MUST NOT be used to convert an OCR attempt into `NOT_SUBMITTED` — a poor-quality or unclassified document is still a document OCR was applicable to; its outcome is `UNREADABLE`, not absence.

**Decision 4 — Malformed-output handling. FROZEN.**

> DP-001 §11's original, never-frozen proposal ("malformed OCR output rejected before persistence") is superseded. OCR follows DP-003's governing principle exactly: any OCR attempt that cannot establish usable text — whether the underlying cause would colloquially be called "unreadable" or "malformed" — is persisted as `INCONCLUSIVE` with `OCR_UNREADABLE`, never silently discarded. Decision 2 means there is no separate "malformed" category distinct from `UNREADABLE` for OCR to begin with — this decision closes the DP-001-vs-DP-003 tension (§4) explicitly rather than leaving it latent, superseding DP-001's stale (never-frozen) row.
>
> `UNAVAILABLE` remains structurally distinct from `UNREADABLE`: `UNREADABLE` means OCR ran and could not establish usable text; `UNAVAILABLE` means OCR could not meaningfully run at all (engine down, timeout, dependency failure — the existing `CapabilityUnavailableError` path). This distinction is load-bearing for Decision 9's retry semantics.

**Decision 5 — Reason codes. FROZEN.**

> `OCR_UNREADABLE` (spec-blessed, EVD-3.14) is reused for the `UNREADABLE` outcome. `MODEL_UNAVAILABLE`/`AMBIGUOUS_DOCUMENT_CAPTURE` are reused unchanged for their existing meanings. No further OCR-specific reason codes are coined in Phase 3 (no `OCR_EMPTY_TEXT`, `OCR_LOW_CONFIDENCE`, `OCR_INVALID_OUTPUT`, `OCR_PARSE_FAILURE`, or similar) — carrying forward DP-003's own coinage discipline explicitly: **a reason code exists because the distinction matters operationally or semantically, not merely because it is technically distinguishable.** Decision 2's two-outcome vocabulary gives no operational distinction finer-grained codes would actually serve yet.

**Decision 6 — Confidence/quality scoring. FROZEN.**

> No confidence or quality field is added to `OcrExtractionResult`/`OCRExtraction` for the deterministic Phase 3 implementation, matching DP-003 Decision 4's precedent exactly — a deterministic stub has no genuine confidence signal to report, and a populated-but-meaningless placeholder would violate EVD-3.13's documented-semantics requirement the moment it's set.
>
> Recorded for whichever future phase introduces a real (non-deterministic) OCR adapter: "OCR confidence" is not one well-defined concept — document-level, field-level, character-level, engine-native, and calibrated-probability confidence are not interchangeable, and that phase's own discovery must decide which (if any) apply, not inherit an assumption from this document.

**Decision 7 — `OcrExtractionResult`/`OCRExtraction` schema shape. FROZEN.**

> `raw: str` is added alongside the existing `fields: dict[str, str]`, matching `MrzResult`/`BarcodeQrResult`'s shape:
> ```python
> class OcrExtractionResult(BaseModel):
>     raw: str
>     fields: dict[str, str]
> ```
> OCR naturally produces two distinct representations — the full raw recognized text, and an informal, non-canonical field-level interpretation of it — and the current fields-only shape has no place for the former. `fields` stays informal/non-canonical, per the same DP-001 Decision 7 reasoning already governing MRZ/Barcode: it is source-evidence, not the canonical cross-source representation, which remains `DOCUMENT_FIELD_EXTRACTION`'s job alone (Phase 4).

**Decision 8 — Deterministic implementation shape. FROZEN.**

> Phase 3's OCR implementation is a full marker-driven stand-in, mirroring `DeterministicBarcodeDecoder`'s pattern exactly — no equivalent to MRZ's "real check-digit validator" subset exists for OCR (no standards-defined algorithm comparable to ICAO 9303 check digits operates on recognized text). The marker mechanism follows the same exact-prefix-only, fail-safe, private-implementation-scaffolding rules DP-004's marker-mechanism safety boundary already established and HV-011 already hostile-tested for the pattern generally.
>
> The deterministic implementation's job is to prove the **architecture** — outcome mapping, persistence, `HIGHLY_SENSITIVE` encryption classification, retry/reusability semantics, concurrency (including cross-capture non-interference), tenant isolation, exception-taxonomy propagation, adversarial-Unicode handling in whatever text the stand-in emits, partial-stage independence, and policy/Decision-Engine visibility — never to prove OCR itself can recognize real documents. That proof is a real adapter's job, in a later phase this document does not scope.

**Decision 9 — Reusable-vs-retryable matrix extension. FROZEN.**

> | Outcome | Reusable? | Retryable? |
> |---|---|---|
> | `VALID` | Yes | No |
> | `UNREADABLE` | Yes | No |
> | `UNAVAILABLE` | No | Yes |
>
> A direct extension of the existing `_is_reusable()` logic — no code change is needed to already produce this answer; this decision confirms it as intended, exactly as DP-003 Decision 9 did for MRZ/Barcode. `UNREADABLE` is deliberately reusable, not retryable: re-running the same deterministic capability against the same image bytes cannot produce a different answer, so blind retry wastes work without improving anything. A future provider-level retry strategy for genuinely transient infrastructure failures remains available through the separate `UNAVAILABLE`/retryable path — this decision does not foreclose that, it only says a content-level `UNREADABLE` finding is not itself grounds for automatic retry.

**Decision 10 — Sensitivity classification reassessment. FROZEN — no change.**

> `OCR_EXTRACTION` remains `HIGHLY_SENSITIVE` (DP-001 Decision 1), already encryption-tested (HV-010's parametrized test already covers it). Nothing in this discovery's Part XI trace surfaces a reason to revisit. The document image, the OCR raw text, the OCR fields, and any future canonical identity data each need classification-appropriate protection independently — this decision only confirms `OCR_EXTRACTION`'s own boundary is unchanged, not that all four are the same concern.

**Decision 11 — Reconciliation architecture. FROZEN — deferred to Phase 4; only one constraint carries forward.**

> No reconciliation architecture is designed or frozen by this document. The full open-question set (§9) — precedence, conflict definition, absence-vs-contradiction, confidence participation, `extensions` eligibility, reconciliation's own status vocabulary, provenance/supersession behavior, rerun triggers, Decision Engine consumption — is carried forward in full to Phase 4's own dedicated discovery, to be resolved there, not inferred here by analogy to Phase 3's decisions.
>
> The one constraint recorded now, because it is already established by EVD-3.25/DEC-5.22/Invariant-02-§2.5 rather than invented by this document: **reconciliation MUST NOT silently adjudicate conflicting evidence through implementation precedence.** Raw per-source evidence (`OCR_EXTRACTION`, `MRZ`, `BARCODE_QR`) stays independently observable regardless of what any future reconciliation stage does (already structurally guaranteed by DP-001 Decision 2), and a source's stronger internal validity check (e.g., MRZ's check-digit algorithm) does not, by itself, establish precedence over a source with a weaker one — that would itself be an implicit-precedence resolution EVD-3.25.1 forecloses. Everything else about reconciliation's actual mechanics is explicitly left to Phase 4.

---

## 11. Conformance/test strategy

Same layering as DP-003/DP-004:
- `tests/unit/` — `DeterministicOCREngine`'s outcome branches (mirroring `DeterministicMRZParser`/`DeterministicBarcodeDecoder`'s test pattern), marker-safety-boundary confirmation, `_OCR_OUTCOME_MAP` exhaustiveness.
- `tests/integration/` — full round-trip per outcome state, retry-convergence both directions, ambiguity extended to the new stage, partial-stage independence, full pipeline-through-policy proof (mirroring every one of DP-004/HV-011's established patterns).
- HV-012, once Phase 3 lands, scoped narrowly to OCR alone (Decision 0) — same discipline HV-011 just proved works: adversarial OCR-output text (SEC-7.21's "unexpected Unicode" category, directly cited in this discovery, §6 point 3), marker-boundary hostile inputs, concurrency at the new call site plus cross-capture non-interference, exception injection, tenant isolation extended to five stages, full N-way partial-stage independence.

---

## Appendix — raw discovery source

The full requirement-by-requirement spec trace and the full repository inventory this document synthesizes (exact Protocol signatures, dataclass/schema fields, the complete EVD-3.25/DEC-5.22 context, and the full whole-repo grep sweep) are available in this session's transcript and can be re-expanded on request — not reproduced in full here, per the same navigability rationale DP-001/DP-003's own appendices state.
