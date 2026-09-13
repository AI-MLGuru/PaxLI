# DP-001 — Document Processing Discovery & Reconciliation

**Status:** RECONCILIATION COMPLETE — all 7 decisions frozen (§16). No production code has been changed during discovery or reconciliation. Implementation is now authorized to proceed per the frozen decisions and the phase plan (§17), starting with Phase 1.
**Scope:** the first real document-processing pipeline (quality, classification, OCR, MRZ, barcode/QR, authenticity) as the first genuine producer of `EvidenceResult` rows.
**Method:** full trace of `docs/specification/part-03` through `part-11` for every document-relevant requirement, plus a full repository inventory of `core/`, `infrastructure/`, `integrations/`, `apps/`, `tests/`, and prior foundation/decision records. Citations below are `file:line`.

## Reconciliation log

| # | Decision | Status |
|---|---|---|
| 1 | Document `EvidenceResultType` classification | **FROZEN** — see §16 |
| 2 | Typed `EvidenceResult` lineage (composite vs. several rows) | **FROZEN** — see §16 |
| 3 | Capability-oriented document processing boundary | **FROZEN** — see §16 |
| 4 | Synchronous document processing boundary | **FROZEN** — see §16 |
| 5 | V1 document-type catalog | **FROZEN** — see §16 |
| 6 | Basic authenticity scope | **FROZEN** — see §16 |
| 7 | `DOCUMENT_FIELD_EXTRACTION` schema shape (was Open Question 6) | **FROZEN** — see §16 |

---

## 1. Scope

In scope for this discovery: everything needed to take a raw `DOCUMENT` capture (`core/evidence/`) through quality/classification/OCR/MRZ/barcode/authenticity processing into `EvidenceResult` rows (`core/evidence_result/`) that the existing, already-hardened Decision Engine can evaluate — without modifying session-lifecycle semantics, Decision Engine semantics, or any of the WF-002–HV-009 frozen contracts.

Out of scope for this discovery (and therefore not addressed below beyond noting where they intersect): the Face and Liveness pipelines (same architectural shape, deliberately deferred to their own discovery once the Document slice proves the pattern), and any real ML model selection/training.

---

## 2. The headline finding — a genuine spec/implementation conflict

**RESOLVED — see Decision 1 (§16), FROZEN.** Left in place below as the discovery record of the conflict as originally found; the frozen resolution is more precise than the fix first proposed here (a payload-content-driven four-type reclassification, not a blanket seven-type one).

Before the requirement matrix: one finding is important enough to lead with, because it is exactly the kind of thing CLAUDE.md requires be surfaced rather than silently resolved.

**Part XI §11.7 (`part-11-data-protection-and-privacy.md:108-119`)** is unambiguous:

> "Identity documents, selfies, videos, images, scans, and related media are `HIGHLY_SENSITIVE` unless stricter classification applies."

**The current implementation classifies every document-related `EvidenceResultType` as merely `SENSITIVE`, not `HIGHLY_SENSITIVE`** (`core/evidence_result/classification.py:20-35`):

```python
EvidenceResultType.DOCUMENT_QUALITY: DataClassification.SENSITIVE,
EvidenceResultType.DOCUMENT_CLASSIFICATION: DataClassification.SENSITIVE,
EvidenceResultType.OCR_EXTRACTION: DataClassification.SENSITIVE,
EvidenceResultType.DOCUMENT_FIELD_EXTRACTION: DataClassification.SENSITIVE,
EvidenceResultType.MRZ: DataClassification.SENSITIVE,
EvidenceResultType.BARCODE_QR: DataClassification.SENSITIVE,
EvidenceResultType.DOCUMENT_AUTHENTICITY: DataClassification.SENSITIVE,
```

The module's own docstring already flags this as provisional: *"This is an initial, defensible mapping, not a final security-reviewed one — flagged in the Foundation-008 closure record"* (`classification.py:1-15`).

**This is not a cosmetic label.** `SqlAlchemyEvidenceResultRepository` keys at-rest encryption directly off `classify()` — only `HIGHLY_SENSITIVE` payloads get AES-256-GCM encrypted; everything else is stored as plaintext `result_json`. Under the current mapping, **OCR-extracted names/DOB/document numbers, raw MRZ strings, and barcode/QR payloads would all be persisted as plaintext JSON in Postgres**, not encrypted — for content the specification explicitly designates `HIGHLY_SENSITIVE`.

There is also an internal inconsistency worth noting: the separate field-name-based sanitization mechanism (`core/security/classification.py:41-66`) already treats `"document"`, `"image"`, `"document_image"`, `"raw_document_payload"` as `HIGHLY_SENSITIVE_FIELDS` for log/audit redaction — so one part of the codebase already treats document content as highly sensitive while the `EvidenceResult`-type classification (which governs actual at-rest encryption) does not. The two mechanisms were never reconciled.

Per CLAUDE.md's conflict-resolution rule, I am not fixing this silently. It is Explicit Decision #1 in §16 below. My recommendation is stated there, but the decision belongs to you.

---

## 3. Normative requirement matrix

Grouped by spec part; `→` shows the implementation consequence. This is not exhaustive prose repetition of the spec — see the raw citations in the appendix-style detail the two discovery agents produced (available on request) for the full quote-by-quote trace. This table is the load-bearing subset.

### Part III — Evidence Semantics

| Requirement | Existing implementation? | Consequence |
|---|---|---|
| §3.5 taxonomy: `DocumentQuality/Classification/OCRExtraction/DocumentFieldExtraction/MRZ/BarcodeQR/DocumentAuthenticity` are **PREREQUISITE: v1.0**, not deferred | `EvidenceResultType` enum has all 9 document-related members (`enums.py:21-43`) | Taxonomy exists; **zero of these types (except generic placeholder use of 2) have ever been exercised beyond their own definition** |
| EVD-3.6.1: each type needs a closed status/result vocabulary | Generic `EvidenceResultStatus` (6 members) shared by all types; per-type schemas exist but define no domain-specific statuses (e.g. no MRZ check-digit-failure state distinct from generic `FAIL`) | Must decide whether the shared 6-status vocabulary is sufficient for document types or whether per-type result payloads need to carry finer-grained sub-status inside `result` |
| EVD-3.7.2/3.7.3: infra failure ≠ FAIL; can't-determine → INCONCLUSIVE | `EvidenceResultStatus.UNAVAILABLE` exists and is already handled by the evaluator's `_UNSATISFYING_STATUSES` (confirmed via `docs/decisions/WF-006-part-iv-conformance.md:319-326`) | Mechanism exists on the consumption side; nothing on the production side has ever set it |
| EVD-3.9.4: integrity failure → INCONCLUSIVE | Already built and HV-009-tested for the *encrypted* path (AES-GCM auth failure → `EngineReasonCode.EVIDENCE_UNAVAILABLE`) | Reusable as-is; a document pipeline gets this for free once its results flow through `EvidenceResultService` |
| EVD-3.10: immutability — reprocessing is a new object, never an update | Structural (`EvidenceResultRepository` has no `update()`), already fixed for cross-session/cross-tenant supersession (HV-009 Findings A/B) | Reusable as-is |
| EVD-3.12.3/3.12.4: quality thresholds must be policy-defined, not hardcoded; insufficient quality → INCONCLUSIVE | `ThresholdDefinition`/`ThresholdRef` mechanism exists and is model/version-bound (`core/policy/thresholds.py`) | Reusable as-is — a document-quality threshold is mechanically identical to a face-match threshold |
| EVD-3.14: reason-code catalog names `OCR_UNREADABLE, DOCUMENT_UNSUPPORTED, MODEL_UNAVAILABLE, MODEL_TIMEOUT, IMAGE_TOO_BLURRY, PROVIDER_TIMEOUT, INSUFFICIENT_SIGNAL` | Not present anywhere in the codebase — no reason-code enum for evidence-level (as opposed to `EngineReasonCode`, which is decision-level) codes exists yet | **Missing capability** — needs a home (see §14, Open Question 3) |
| EVD-3.17: explicit lineage example "capture → quality → OCR → identity consistency" | `EvidenceResult.source_reference` (capture→result) and `parent_evidence_result_ids` (result→result) exist and are now validated tenant/session-safe (HV-009 Finding B) | Reusable as-is; the *shape* of a multi-stage pipeline's lineage graph still needs designing (§6) |
| EVD-3.24: invalid/malformed evidence → safe outcome before decisioning | `validate_result_payload()` + Pydantic `SCHEMA_REGISTRY` already reject malformed payloads at `create()` time | Reusable as-is, but current schemas are semantically empty (see §4) |
| §3.33: Advanced document authenticity and expanded external-identity integrations are the only document-adjacent items **explicitly deferred**; base document evidence types themselves are not | No authenticity-signal taxonomy exists beyond a placeholder `authenticity_signals: tuple[str, ...]` schema field | Must decide the "basic vs advanced" authenticity boundary explicitly (Open Question 2) |

### Part IV — Verification Workflow

| Requirement | Existing implementation? | Consequence |
|---|---|---|
| WF-4.11/4.12: internal processing execution states (`NOT_STARTED, RUNNING, RETRYING, SUCCEEDED, TIMED_OUT, FAILED`) must map to a Part III evidence state before Decision Engine acceptance | **Does not exist at all.** `PROCESSING` in the real lifecycle does nothing but call `evaluate_and_persist()` synchronously (`core/verification/workflow.py:131-156`) | **This is the central architectural gap** — see §9/§14 Open Question 1 |
| WF-4.15.5: retry exhaustion → final INCONCLUSIVE with stable reason code | Mechanism exists at the Decision Engine level (this session's HV-009 fix); nothing exists at the "OCR call retry" level, because no OCR call exists | Needs an inference-layer retry/circuit-breaker wrapper (§10) |
| WF-4.34: durable async job infra, advanced human review, session resumption are **DEFERRED, TARGET v1.1** | `infrastructure/queue/` is an empty package; `apps/worker/` is empty (confirmed) | Confirms: a synchronous-processing design for the first vertical slice is spec-consistent, not a shortcut — see §9 |

### Part V — Decision Engine

| Requirement | Existing implementation? | Consequence |
|---|---|---|
| DEC-5.1.1: document components MUST NOT independently declare a final verdict | Already structurally enforced — no component in this codebase has a path to writing a `DecisionResult` except `DecisionOrchestrator` | Reusable as-is; a `DocumentProvider` implementation only ever produces `EvidenceResult`s |
| DEC-5.20: thresholds "MAY be used for... document confidence" | `ThresholdDefinition` is evidence-type-agnostic | Reusable as-is |
| DEC-5.34: model version interaction / calibration-model-mismatch | Already built and tested (`_check_calibration_compatibility`, DE-003 §17.2) | Reusable as-is |

### Part VI–VIII — API, Security, Conformance

| Requirement | Existing implementation? | Consequence |
|---|---|---|
| API-6.8: `POST /verification-sessions/{id}/document` | Already exists, already working, identical to `/selfie`/`/liveness` (`apps/api/paxli_api/routers/evidence.py:154-179`) | Reusable as-is for capture; no new endpoint needed for capture |
| SEC-7.22: uploaded files untrusted; MIME sniffing not filename; malformed media fails safe; no filesystem exposure via attacker-controlled content | `verify_evidence_media()` does magic-byte sniffing (JPEG/PNG/WEBP only, **no PDF**) | A document-processing library that parses attacker-controlled bytes (OCR/MRZ/barcode decoders) is itself a new attack surface SEC-7.22.5 explicitly names — must be threat-modeled before selecting a library |
| CONF-8.32: any real provider integration needs a governed adapter contract | `integrations/identity/` exists as an empty stub — the intended home, never built | Confirms external-identity-provider work is genuinely separate from the Document pipeline itself |
| CONF-8.33: model artifacts need identifiable versions, documented reproducible evaluation, versioned calibration | `ModelReference` model exists and is already integrity-covered; no model registry exists (`models/registry/.gitkeep` is an empty placeholder) | A real model needs a version-tracking convention decided before Phase 2 (§17) |

### Part IX — Deferred Architecture (the explicit boundary)

| Capability | Status | Citation |
|---|---|---|
| Advanced document authenticity (chip/NFC, cryptographic, tamper, issuer-specific, expanded document families) | **DEFERRED** | `part-09:186-194` |
| Expanded external identity integrations (NIMC, BVN, institutional registries) | **DEFERRED / TARGET v1.1** | `part-09:196-205`; `part-03:562-566` |
| Base document evidence types (quality/classification/OCR/MRZ/barcode/basic authenticity) | **NOT deferred — PREREQUISITE v1.0** | `part-03:91-113` |

DEF-9.15.2 is load-bearing for design: *"Absence of authenticity capability MUST NOT be interpreted as authenticity success."* If basic authenticity checking isn't built yet, `DocumentAuthenticity` must resolve to `NOT_REQUIRED`/`UNAVAILABLE`, never a default `PASS`.

### Part X — Reliability

| Requirement | Existing implementation? | Consequence |
|---|---|---|
| REL-10.21: inference failure (crash, timeout, **malformed output**, incompatibility) → processing failure or `INCONCLUSIVE`; invalid model output MUST NOT become valid evidence | `validate_result_payload()` already rejects malformed output at `create()` time — this requirement is *already satisfied structurally*, once a real producer exists | Reusable as-is |
| REL-10.15: partial pipeline failure preserves completed evidence; DE determines final outcome | `EvidenceResult` immutability + `list_effective_for_session()` already implement this generically | Reusable as-is — if OCR succeeds but MRZ fails, the OCR `EvidenceResult` row is unaffected |
| `infrastructure/reliability/minio_policies.py` pattern (CircuitBreaker + RetryPolicy + timeout + typed exception + metrics) | Exists for MinIO and Postgres; **no analogous `inference_policies.py` exists** | Direct template to copy for a `guarded_infer()` wrapper (§10) |

### Part XI — Privacy

Covered in §2 above (the headline conflict). Additional load-bearing points:
- PRV-11.7.6: temporary processing copies (e.g. deskewed/cropped intermediate images during OCR preprocessing) must follow lifecycle/deletion rules — this needs an explicit answer for whatever OCR library is chosen (does it write temp files to disk?).
- PRV-11.43.1: production document evidence must not become model-training data "by technical default" — relevant the moment any model is fine-tuned on real submissions.

---

## 4. Existing implementation inventory

**`EvidenceResultType`** (`core/evidence_result/enums.py:21-43`) — 14 members total. Of the 9 document/identity-related types, **only `DOCUMENT_QUALITY` and `OCR_EXTRACTION` have ever been referenced anywhere outside their own enum/schema/classification definitions** — and even those references are generic mechanism-plumbing tests using placeholder field names (policy-tree structural tests, schema-shape tests), never real content. `DOCUMENT_CLASSIFICATION`, `DOCUMENT_FIELD_EXTRACTION`, `MRZ`, `BARCODE_QR`, `DOCUMENT_AUTHENTICITY`, `IDENTITY_CONSISTENCY` have **zero references anywhere** beyond their own definitions.

**`EvidenceResultStatus`** — 6 members (`NOT_REQUIRED, NOT_SUBMITTED, UNAVAILABLE, INCONCLUSIVE, PASS, FAIL`), matches Part III's closed set exactly.

**Schemas** (`core/evidence_result/schemas.py:16-95`) — real Pydantic classes exist and are enforced for all 14 types, but are maximally generic placeholders:
```python
class OcrExtractionResult(BaseModel):
    fields: dict[str, str]

class DocumentFieldExtractionResult(BaseModel):
    fields: dict[str, str]        # byte-identical to OcrExtractionResult

class MrzResult(BaseModel):
    raw: str
    fields: dict[str, str]        # no ICAO 9303 field breakdown at all

class BarcodeQrResult(BaseModel):
    raw: str
    fields: dict[str, str] = {}   # no symbology/format field
```
No per-field confidence, no bounding boxes, no ICAO 9303 field names (document code, issuing state, surname, given names, document number, nationality, DOB, sex, expiry, check digits), no barcode symbology distinction (PDF417 vs QR vs Code128).

**Policy condition layer** (`core/evidence_result/schema_catalog.py`) can only check top-level Pydantic field names (`supports_field("OCR_EXTRACTION", "fields")` → `True`), never a nested key like `fields.document_number`. **No policy can currently condition on a specific extracted field value** — only on the presence of the whole `fields` dict. This is close to useless for real document policy logic ("reject if document is expired," "require document_number present").

**Capture side** (`core/evidence/enums.py`) — `EvidenceType.DOCUMENT` is a single, undifferentiated value. No passport/national-ID/driver's-license distinction, no front/back distinction, no multi-page grouping. The upload path (`apps/api/paxli_api/routers/evidence.py:154-179`) is byte-for-byte identical to `/selfie`/`/liveness` except the enum value. Media validation accepts JPEG/PNG/WEBP only — **no PDF support**, so a multi-page document must be multiple independent image uploads with nothing linking them as sides of one physical document.

**Provider contracts already exist as pure abstractions with zero implementations**:
```python
# core/document/provider.py
@dataclass(frozen=True)
class DocumentEvidence:
    document_type: str | None
    fields: dict[str, str]
    quality_score: float | None = None
    authenticity_signals: tuple[str, ...] = ()

class DocumentProvider(ABC):
    @abstractmethod
    async def extract_evidence(self, image: bytes) -> DocumentEvidence:
        raise NotImplementedError
```
`FaceProvider`/`LivenessProvider` are identically-shaped sibling ABCs. All three have **zero concrete implementations anywhere**, confirmed via WF-006 Finding K (`docs/decisions/WF-006-part-iv-conformance.md:319-330`, written this session, still current): *"`DocumentProvider`/`FaceProvider`/`LivenessProvider` are abstract base classes with zero implementations, and `apps/worker/` is empty... that's a separate, much larger undertaking."*

**The lifecycle gap**: `VerificationWorkflowService.submit()`'s `PROCESSING` branch (`core/verification/workflow.py:131-156`) does exactly one thing — call `DecisionOrchestrator.evaluate_and_persist()` synchronously, then advance straight to `COMPLETED`. There is **no pause, no dispatch, no queue step** between a session entering `PROCESSING` and the Decision Engine running. `apps/worker/` contains only `.gitkeep` and empty `__init__.py` files. `infrastructure/queue/` is an empty package. This is confirmed spec-consistent, not a gap in isolation — WF-001 §15 (`docs/decisions/WF-001-verification-workflow-semantics.md:384-386`) explicitly defers durable async job infrastructure to TARGET v1.1.

**Zero OCR/ML dependencies exist anywhere** — confirmed via full-repo grep and `pyproject.toml` inspection. No PaddleOCR, OpenVINO, Tesseract, pyzbar, onnx, torch, tensorflow, ICAO-parsing library, or barcode-decoding library is referenced anywhere in the codebase.

**Test coverage**: zero tests exercise `DOCUMENT_CLASSIFICATION`, `DOCUMENT_FIELD_EXTRACTION`, `MRZ`, or `BARCODE_QR` in any capacity. `DOCUMENT_QUALITY` and `OCR_EXTRACTION` have only generic schema-shape/policy-tree-mechanism tests with placeholder values — nothing tests real content, decision evaluation, or an end-to-end flow for any document type.

---

## 5. Existing reusable primitives

These require zero new design work — the document pipeline gets them for free by virtue of producing ordinary `EvidenceResult` rows through the existing service:

- Server-computed, tamper-evident `integrity_reference` (now score/quality-complete, HV-009 Finding D)
- Structural immutability (no `update()`), cross-session/cross-tenant-safe `supersede()` (HV-009 Findings A + final check)
- Cross-session/cross-tenant-safe provenance validation for `source_reference`/`parent_evidence_result_ids` (HV-009 Finding B)
- AES-256-GCM at-rest encryption for whatever is classified `HIGHLY_SENSITIVE`, with tamper detection converting cleanly to `INCONCLUSIVE`/`EVIDENCE_UNAVAILABLE` (HV-009 Finding C)
- `EvidenceRequirement`/`EvidenceRequirementLevel`, evidence-type-agnostic, already works for any registered type including every document type
- `ThresholdDefinition`/`ThresholdRef` calibration binding, including model-version-mismatch protection (DE-003 §17.2, already tested)
- Three-valued (`TRUE/FALSE/INDETERMINATE`) condition evaluation with safe-absence semantics
- `infrastructure/reliability/minio_policies.py`'s `CircuitBreaker + RetryPolicy + timeout + typed exception + metrics` pattern — a direct template for a future inference-call wrapper
- The full audit/idempotency/tenant-isolation machinery already proven across WF-002–HV-009

---

## 6. Document evidence lifecycle — the lineage question

Part III §3.17's own example (`part-03:298`) names the intended shape directly: **capture → quality → OCR → identity consistency**. Combined with the taxonomy in §3.5, the natural lineage graph is:

```
Evidence (capture, EvidenceType.DOCUMENT)
       │
       │ source_reference
       ▼
EvidenceResult(DOCUMENT_QUALITY)
       │
       ├──────────────┬──────────────┬──────────────┐
       ▼              ▼              ▼              ▼
DOCUMENT_          OCR_          MRZ            BARCODE_QR
CLASSIFICATION   EXTRACTION   (if MRZ present) (if barcode present)
       │              │              │              │
       └──────────────┴──────┬───────┴──────────────┘
                              ▼
                    DOCUMENT_FIELD_EXTRACTION
                    (reconciled/normalized fields
                     from OCR + MRZ + barcode)
                              │
                              ▼
                    DOCUMENT_AUTHENTICITY
                              │
                              ▼
                    IDENTITY_CONSISTENCY
                    (cross-checks against FaceMatch,
                     ExternalIdentityProvider, etc.)
```

**FROZEN as Decision 2 (§16):** several typed `EvidenceResult` rows, not one composite result — each with `source_reference` pointing at the capture and/or `parent_evidence_result_ids` pointing at its upstream stage(s), per the exact wiring rule frozen in §16. This is directly supported by:
- EVD-3.17's own lineage language ("derived evidence must identify source evidence")
- REL-10.15 (partial pipeline failure must preserve completed evidence) — a single composite row would make "OCR succeeded, MRZ failed" inexpressible without either a partially-null mega-object or two competing writes to one row (which immutability forbids anyway)
- The existing schema catalog's one-schema-per-type design, which a composite result would have to abandon or awkwardly nest

---

## 7. EvidenceResult mapping

Concretely, per stage:

| Stage | `EvidenceResultType` | `status` values in play | `result` schema needs |
|---|---|---|---|
| Quality gate | `DOCUMENT_QUALITY` | `PASS/FAIL/INCONCLUSIVE` (blur/glare/crop) | Existing `quality_score: float` is probably sufficient; `quality` top-level field already universal |
| Classification | `DOCUMENT_CLASSIFICATION` | `PASS` (classified) / `INCONCLUSIVE` (ambiguous) / `FAIL` (unsupported) | Needs a real enum/catalog of document types (Open Question 4) instead of a bare `document_type: str` |
| OCR | `OCR_EXTRACTION` | `PASS/INCONCLUSIVE (OCR_UNREADABLE)/UNAVAILABLE` | Needs per-field confidence, not just raw text |
| MRZ | `MRZ` | `PASS/FAIL (checksum)/NOT_SUBMITTED (no MRZ)/INCONCLUSIVE` | Needs real ICAO 9303 field breakdown + check-digit validation result |
| Barcode/QR | `BARCODE_QR` | `PASS/NOT_SUBMITTED/INCONCLUSIVE` | Needs a `symbology` field |
| Field reconciliation | `DOCUMENT_FIELD_EXTRACTION` | `PASS/INCONCLUSIVE (conflicting sources)` | Needs a defined reconciliation algorithm (OCR vs MRZ vs barcode disagreement) — currently unspecified anywhere |
| Authenticity | `DOCUMENT_AUTHENTICITY` | `PASS/FAIL/NOT_REQUIRED (no capability yet, per DEF-9.15.2)` | `authenticity_signals: tuple[str,...]` exists but is an empty placeholder — needs real signal definitions for whatever "basic" authenticity means (Open Question 2) |
| Identity consistency | `IDENTITY_CONSISTENCY` | `PASS/FAIL/INCONCLUSIVE` | Algorithm entirely unspecified (Open Question 5) |

None of this requires new Decision Engine code — every field above is either a `_UNIVERSAL_FIELDS` member (`status`, `score`, `quality`) or lives inside `result`, exactly like every other evidence type already evaluated.

---

## 8. Decision Engine integration

**No new Decision Engine semantics are needed.** A policy requiring `DOCUMENT_QUALITY`/`OCR_EXTRACTION`/etc. works exactly like requiring `FACE_MATCH` today:

```python
EvidenceRequirement(evidence_type="OCR_EXTRACTION", level=EvidenceRequirementLevel.REQUIRED)

Rule(
    condition=EvidenceCondition(
        evidence_type="DOCUMENT_AUTHENTICITY", field="status",
        operator="==", expected_value="PASS",
    ),
    outcome=DecisionOutcome.VERIFIED,
    reason_code="POLICY:DOCUMENT_AUTHENTIC",
)
```

The one real gap: **no policy can condition on a nested field inside `result`** (e.g., `fields.document_number` or a per-field OCR confidence) because `EvidenceResultSchemaCatalog.supports_field()` only checks top-level Pydantic field names. This doesn't block Phase 1 (status/score/quality-level conditions work today), but blocks any policy wanting field-level logic ("require document_number present and non-empty"). This is Open Question 6 — worth deciding now even if not built now, since it shapes whether `DocumentFieldExtractionResult`'s schema should be flattened (top-level fields per identity attribute) rather than a nested `dict`.

---

## 9. Inference/provider boundary options — comparative analysis

Recall the three hypotheses you posed. Discovery's job is to check them against what actually exists, not just prefer one on priors.

**Option A — deterministic/stub capability.** Proves orchestration and `EvidenceResult` semantics without committing to a model runtime. Given that **every single document evidence type today has zero real usage anywhere in the codebase**, this has real value: it would let the FIRST tests of "does an `EvidenceResult` with `OCR_EXTRACTION` actually flow through policy evaluation to a decision" exist at all, closing the "generic mechanism test, never real content" gap the repo inventory found everywhere. Cost: doesn't produce a usable KYC path yet.

**Option B — real OCR provider immediately.** Matches "first real vertical slice" framing directly, but the repository inventory shows **nothing exists to build on** — no reliability wrapper for inference calls, no model versioning convention wired up, no ICAO 9303 field schema, no barcode symbology handling, and (per §2) an unresolved data-classification conflict that would mean real extracted PII goes to disk unencrypted from day one. Building B before A means debugging real-OCR-library integration issues, orchestration-boundary issues, and schema-design issues simultaneously — exactly the kind of undifferentiated risk this project's own discipline (WF/DE/HV) has consistently avoided by separating "does the contract work" from "does the real implementation work."

**Option C — hybrid, capability ports with a deterministic baseline and a real adapter slotted in later.** This is what the evidence actually supports as the right shape, for reasons independent of your stated bias:
- `infrastructure/reliability/minio_policies.py` is a proven, in-repo template for exactly this kind of swappable-backend + reliability-wrapper design (`CircuitBreaker`/`RetryPolicy`/typed exception/metrics), already used for MinIO and Postgres.
- `core/document/provider.py`'s `DocumentProvider` ABC already exists in this shape (a capability port with zero implementations) — Option C is not new architecture, it's *finishing* architecture that's already half-built and named in a foundation's own scope boundary.
- CLAUDE.md's own "capability-oriented interfaces" rule and "infrastructure follows a demonstrated capability requirement" rule both favor a port-based design over hard-wiring one library, without requiring a real model to exist yet.
- The one-composite-vs-several-results question (§6) and the field-level-condition question (§8, Open Question 6) both need to be validated against SOMETHING before a real OCR/MRZ library choice is made — a deterministic stub is the cheapest way to validate them.

**FROZEN as Decision 3 (§16):** Option C, refined during reconciliation into six independently replaceable capability ports (not the existing monolithic `DocumentProvider`, which is retired — see §16), sequenced so the deterministic baseline for `QualityAssessor`/`DocumentClassifier` (a) proves the orchestration/lineage design decisions in §6–8 first, then (b) `OCREngine`/`MRZParser`/`BarcodeDecoder`/`AuthenticityChecker` are interface-designed but implementation-deferred until the field-schema and document-catalog decisions land, then (c) a real adapter is slotted in behind whichever port is implemented first, once a specific document type / library is chosen.

---

## 10. Infrastructure requirements

| Need | Required now | Optional later | Deferred | Unjustified now |
|---|---|---|---|---|
| A `DocumentProcessor` orchestration component (calls the port(s), writes `EvidenceResult` rows) | ✅ | | | |
| `DocumentProvider`/quality/classifier/OCR/MRZ/barcode capability ports (interfaces only) | ✅ | | | |
| Deterministic stub implementation(s) of the above | ✅ | | | |
| A `guarded_infer()`-style reliability wrapper mirroring `minio_policies.py` | ✅ | | | |
| A real OCR/MRZ/barcode/classification library integration | | ✅ (Phase 2+) | | |
| A document-type catalog / enum | ✅ (even if short, per Open Question 4) | | | |
| Multi-page/front-back document grouping in the capture API | | ✅ | | |
| PDF upload support | | ✅ | | |
| A queue/worker/durable async job system | | | ✅ (WF-4.34, TARGET v1.1) | |
| External identity-provider adapters (NIMC/BVN) | | | ✅ (Part IX §9.16, TARGET v1.1) | |
| Advanced/chip-NFC/cryptographic document authenticity | | | ✅ (Part IX §9.15, DEFERRED) | |
| A model registry/serving platform | | | | ✅ — `models/registry/` is an empty placeholder with no demonstrated need yet |
| Redis, Kafka, Celery, Kubernetes, a second database | | | | ✅ — nothing in this discovery demonstrates a need any of these would satisfy that Postgres/MinIO/synchronous processing cannot |

The synchronous-processing implication is important and should be stated plainly: **because durable async job infrastructure is explicitly deferred (WF-4.34), the first vertical slice's document processing must run synchronously inside the request that drives `PROCESSING`** (almost certainly inside `submit()`, before or as part of what calls `evaluate_and_persist()`) rather than being dispatched to a worker. This has a real latency/timeout consequence (Open Question 1) but is spec-consistent, not a shortcut.

---

## 11. Failure/reliability semantics — mapped before implementation, per your instruction

| Failure | Evidence-level outcome | Reason code (evidence, Part III §3.14) | Decision-level outcome (if decision-relevant) |
|---|---|---|---|
| Image unreadable / too blurry to process | `DOCUMENT_QUALITY = FAIL` or `INCONCLUSIVE` per EVD-3.12.4 | `IMAGE_TOO_BLURRY` | Policy-defined (`REVIEW_REQUIRED` or `INCONCLUSIVE`) |
| OCR runtime/model unavailable | `OCR_EXTRACTION = UNAVAILABLE` | `MODEL_UNAVAILABLE` | `INCONCLUSIVE` |
| OCR call times out (after bounded retry, REL-10.9) | `OCR_EXTRACTION = UNAVAILABLE` | `MODEL_TIMEOUT` | `INCONCLUSIVE` |
| OCR executes, produces malformed/unparseable output | Rejected at `create()` by `validate_result_payload()` (REL-10.21.2: "invalid model output MUST NOT become valid evidence") — never persisted as a trusted result | `OCR_UNREADABLE` (recorded via the caller's own recovery path, e.g. a follow-up `INCONCLUSIVE` submission — mirrors the existing `EVD-3.24.3` pattern already documented on `EvidenceResultService.create()`) | `INCONCLUSIVE` |
| MRZ present but checksum fails | `MRZ = FAIL` | (new, ICAO-specific — not in the Part III catalog; needs definition, Open Question 4-adjacent) | Policy-defined |
| No MRZ on document | `MRZ = NOT_SUBMITTED` | — | `NOT_REQUIRED` if policy doesn't need it |
| Barcode/QR decoder unavailable | `BARCODE_QR = UNAVAILABLE` | `MODEL_UNAVAILABLE` | `INCONCLUSIVE` if policy requires it, else `NOT_REQUIRED` |
| Document classified as unsupported type | `DOCUMENT_CLASSIFICATION = FAIL` | `DOCUMENT_UNSUPPORTED` | Policy-defined |
| Partial pipeline failure (OCR ok, MRZ fails) | Each stage's `EvidenceResult` stands independently (REL-10.15.1) | — | Decision Engine evaluates whatever evidence exists; missing MRZ is `REQUIRED_EVIDENCE_MISSING` only if policy required it |
| Encrypted result payload corrupted/tampered | Already built (HV-009 Finding C) | — | `INCONCLUSIVE` / `ENGINE:EVIDENCE_UNAVAILABLE` |
| Document evidence encrypted-at-rest classification wrong (per §2) | N/A — data-protection issue, not a runtime failure | — | N/A |

These are proposed mappings for reconciliation, not frozen decisions — several depend on Open Questions 2 and 4.

---

## 12. Security/privacy implications

- §2's classification conflict is the dominant issue and must be resolved before any real document content is processed, let alone stored.
- SEC-7.22.5 ("media processing MUST NOT expose filesystem/infrastructure access through attacker-controlled content") directly threat-models the choice of OCR/MRZ/barcode library — these libraries commonly shell out, use native codecs, or write temp files, all of which need review before adoption (this is a library-selection-time concern, not something DP-001 resolves).
- PRV-11.7.6 (temporary processing copies) needs an explicit answer once a specific library is chosen — does it write intermediate files to disk, and if so, what's their lifecycle?
- No document-type catalog is a data-minimization question too: `IDENTITY_CONSISTENCY`'s exact inputs are unspecified (Open Question 5), and extracted-field reconciliation logic (Open Question 4) will touch names/DOB/ID numbers — all `SENSITIVE` at minimum per Part XI §11.5, `HIGHLY_SENSITIVE` per the recommended resolution of §2.
- The existing `POST /verification-sessions/{id}/document` endpoint, `EvidenceService.add()`, checksum computation, and media-type sniffing already satisfy SEC-7.22.1–7.22.4 and EVD-3.9.5 for the capture side — no new capture-side security work is needed, only the processing side.

---

## 13. Deferred capabilities (explicit, derived from the spec, not assumed)

```
V1 Document Pipeline (this discovery's scope)
├── DOCUMENT_QUALITY
├── DOCUMENT_CLASSIFICATION
├── OCR_EXTRACTION
├── MRZ
├── BARCODE_QR
├── DOCUMENT_FIELD_EXTRACTION (reconciliation across OCR/MRZ/barcode)
├── DOCUMENT_AUTHENTICITY — BASIC only (scope TBD, Open Question 2)
├── IDENTITY_CONSISTENCY — cross-check against other evidence (algorithm TBD, Open Question 5)
└── EvidenceResult production + Decision Engine integration (no new DE code needed)

Explicitly deferred by the specification itself (not a scoping choice made here)
├── Advanced document authenticity — chip/NFC, cryptographic, tamper detection, issuer-specific, expanded document families (Part IX §9.15)
├── External identity-provider verification — NIMC/BVN/institutional registries (Part IX §9.16, TARGET v1.1)
├── Durable async job/queue infrastructure (Part IV §4.34, TARGET v1.1)
├── Advanced human-review workflow / adjudication tooling (Part IV §4.34, TARGET v1.1)
└── Advanced liveness/PAD (Part III §3.33, TARGET v1.1 — Face/Liveness pipeline's own discovery, not this one)

Not deferred by the spec, but genuinely undefined by it (implementation-level decisions, not spec violations)
├── The specific document-type catalog (passport/national ID/driver's license/etc. — never named anywhere in the spec)
├── Multi-page/front-back document grouping
└── PDF upload support
```

---

## 14. Open architectural questions

1. ~~Where does synchronous document processing actually run?~~ **RESOLVED — Decision 4, FROZEN.**
2. ~~Where is the "basic vs advanced" document authenticity line?~~ **RESOLVED — Decision 6, FROZEN: there is no defensible "basic" signal for V1; the capability is not implemented.**
3. **Where do evidence-level reason codes (Part III §3.14: `OCR_UNREADABLE`, `DOCUMENT_UNSUPPORTED`, etc.) live in code?** No such enum exists today — `EngineReasonCode` is decision-level only. This needs a home (likely `core/evidence_result/reason_codes.py`, mirroring `core/policy/reason_codes.py`'s `POLICY:` namespace pattern) before any component can honestly report `IMAGE_TOO_BLURRY`.
4. **Is there a document-type catalog for v1.0, and if so what's in it?** The spec never names one. Recommend defining a short, explicit list (e.g., passport + one national ID format) rather than trying to build a general document-family classifier immediately — but this is your call, not mine to assume. — see Decision 5.
5. **What does `IDENTITY_CONSISTENCY` actually check?** No section defines its inputs or algorithm. Exact-match on OCR'd name vs. session-provided name? Fuzzy match? DOB tolerance? Cross-check against `ExternalIdentityProvider` when that's eventually built?
6. ~~Should `DocumentFieldExtractionResult` stay a nested `dict[str, str]`, or become a flatter, per-identity-attribute schema?~~ **RESOLVED — Decision 7, FROZEN.**
7. ~~One composite `EvidenceResult` vs. several typed rows per pipeline run (§6)?~~ **RESOLVED — Decision 2, FROZEN.**
8. **The reusable-vs-retryable matrix per `EvidenceResultStatus`.** Decision 4 establishes that a reusable result must be reused and a non-reusable one may be retried-via-supersession, but doesn't define which statuses are which (e.g., is `INCONCLUSIVE` always retryable? Is `UNAVAILABLE` retryable only within some attempt budget, after which it becomes terminal?). Deliberately deferred to Phase 1 implementation/conformance work, not resolved during DP-001 reconciliation — carried forward here so it isn't lost.

---

## 15. Recommended implementation shape

```
DocumentProcessor (orchestration, core/document/)
        │  translates capability domain-results into EvidenceResult rows,
        │  establishes source_reference/parent_evidence_result_ids,
        │  handles retry-as-supersede
        ▼
┌────────────────────────────────────┐
│   Capability Ports (domain results,  │  (interfaces, core/document/;
│   never EvidenceResult)               │   DocumentProvider RETIRED)
├────────────────────────────────────┤
│ QualityAssessor       -> QualityAssessment      │
│ DocumentClassifier    -> DocumentClassification │
│ OCREngine             -> OCRExtraction          │  interface-only until
│ MRZParser             -> MRZExtraction | Absent │  Open Q6 / Decision 5
│ BarcodeDecoder        -> BarcodeExtraction|Absent│ resolved
│ AuthenticityChecker   -> AuthenticityAssessment │
└──────────────┬─────────────────────┘
               │
     ┌─────────┴─────────┐
     ▼                   ▼
Deterministic         Real adapter
baseline               (Phase 3+, behind
(QualityAssessor +     infrastructure/reliability-style
 DocumentClassifier    guarded wrapper)
 only, Phase 1)
               │
               ▼
     EvidenceResultService.create()  (existing, unmodified)
               │
               ▼
     Decision Engine  (existing, unmodified)
```

This is Decision 3 from §9/§16, requires zero changes to `EvidenceResultService`, `DecisionOrchestrator`, or any WF/DE/HV-frozen contract, and lets Phase 1 validate every open architectural question in §14 against two deterministic, fully-controllable capabilities before any real library, model, or field schema is chosen.

---

## 16. Explicit decisions requiring your approval

**Decision 1 — Document `EvidenceResultType` classification. FROZEN.**

> `OCR_EXTRACTION`, `MRZ`, `BARCODE_QR`, and `DOCUMENT_FIELD_EXTRACTION` are classified `HIGHLY_SENSITIVE`. `DOCUMENT_QUALITY`, `DOCUMENT_CLASSIFICATION`, `DOCUMENT_AUTHENTICITY`, `IDENTITY_CONSISTENCY`, and, provisionally, `EXTERNAL_IDENTITY_PROVIDER` remain `SENSITIVE`. Classification is determined by the sensitivity of the **persisted result payload**, not merely by the evidence type's domain — the same principle already governing biometrics (`FACE_EMBEDDING = HIGHLY_SENSITIVE`; `FACE_QUALITY/FACE_MATCH/FACE_DETECTION = SENSITIVE`). `EXTERNAL_IDENTITY_PROVIDER`, and any future per-symbology split of `BARCODE_QR` (e.g. an opaque-reference QR vs. a PDF417 encoding a full identity record), MUST be reassessed against this same payload-content test if their actual payload semantics change.

Rejected: the original blanket "all 7 document types → `HIGHLY_SENSITIVE`" proposal — it would have applied a document-domain exception to a classification model that is otherwise strictly payload-content-driven, over-encrypting three types (`DOCUMENT_QUALITY`, `DOCUMENT_CLASSIFICATION`, `DOCUMENT_AUTHENTICITY`) whose results carry only a score/label/signal-name, never an identity-field value. §11.7 (document *media*) and §11.5 (identity *data*) are two different sections governing two different things; the raw capture image is already correctly `HIGHLY_SENSITIVE` via `EncryptedObjectStorage`'s unconditional encryption regardless of this table, so this table's job is specifically to classify each *result's* payload, not to re-protect the media a second time.

Implementation consequence, deferred to Phase 1 (not done during DP-001): update `EVIDENCE_RESULT_CLASSIFICATION` in `core/evidence_result/classification.py` accordingly.

**Decision 2 — Typed `EvidenceResult` Lineage. FROZEN.**

> PaxLI MUST represent document-processing stages as several typed `EvidenceResult` rows rather than one composite document-processing result.
>
> A processing stage that directly reads a capture Evidence MUST identify that capture through `source_reference`.
>
> A processing stage that consumes one or more previously produced EvidenceResults MUST identify those upstream results through `parent_evidence_result_ids`.
>
> A stage MAY populate both fields when it directly examines the source capture and also consumes upstream processing results.
>
> `parent_evidence_result_ids` is type-agnostic and MAY reference EvidenceResults from other evidence domains where the processing stage semantically depends on them.
>
> A retry that produces a new result for an existing `(tenant_id, session_id, evidence_type)` stage MUST supersede the prior effective result rather than create a second effective result.
>
> Supersession MUST preserve valid tenant, session, evidence-type, and lineage boundaries.
>
> PaxLI MUST NOT introduce a separate pipeline-run or batch identifier for V1 document processing. Processing history MUST be reconstructable through the EvidenceResult lineage graph, supersession relationships, and capture `source_reference`.
>
> A first-class processing-run identifier MAY be introduced in a future architecture only where an independently identifiable processing execution becomes a required semantic or operational entity.

Governing invariant for Phase 1 onward: **EvidenceResults form a provenance graph, not a bag of outputs.**

**Decision 3 — Capability-Oriented Document Processing Boundary. FROZEN.**

> The existing monolithic `DocumentProvider` abstraction (`core/document/provider.py`) is retired and MUST NOT be used as the document-processing boundary — its single `extract_evidence()` call cannot express Decision 2's independent per-stage failure/retry/supersession model.
>
> Document processing MUST expose independently replaceable capability ports for: `QualityAssessor`, `DocumentClassifier`, `OCREngine`, `MRZParser`, `BarcodeDecoder`, `AuthenticityChecker`.
>
> Each capability MUST have an independently defined **domain result** corresponding to its pipeline stage (e.g. `QualityAssessment`, `OCRExtraction` as plain domain types). Capability implementations MUST NOT directly own `EvidenceResult` persistence or lineage management, and MUST NOT be passed persistence identifiers (e.g. a classification `EvidenceResult`'s row ID) — only the domain-level value they need (e.g. `document_type: str`).
>
> `DocumentProcessor` MUST remain responsible for translating capability outputs into typed `EvidenceResult` records, establishing `source_reference` and `parent_evidence_result_ids` per Decision 2's wiring rule, handling supersession/retry semantics, and coordinating Decision Engine integration. `AuthenticityChecker.check(image, document_type)` receives the domain value `document_type` resolved by `DocumentProcessor` from the effective `DOCUMENT_CLASSIFICATION` result; the resulting `EvidenceResult`'s lineage (`parent_evidence_result_ids = (classification.id,)`) is recorded at the `DocumentProcessor`/persistence layer, never inside the capability call itself.
>
> Capability ports MUST permit deterministic and real implementations to be substituted without changing `DocumentProcessor` orchestration or its callers.
>
> Phase 1 MUST implement deterministic `QualityAssessor` and `DocumentClassifier` capabilities only. The `OCREngine`, `MRZParser`, `BarcodeDecoder`, and `AuthenticityChecker` ports MAY be interface-designed during Phase 1 but MUST NOT receive production implementations (deterministic or real) until the field-schema (Open Question 6) and document-catalog (Decision 5) decisions governing their outputs have been resolved.
>
> Real external/model-backed implementations MUST execute behind the established reliability boundary (`CircuitBreaker` + `RetryPolicy` + timeout + typed exception + metrics), mirroring `infrastructure/reliability/minio_policies.py`.
>
> A coarse-grained image-analysis port MUST NOT combine independently failing document-processing stages merely because they consume the same source image.

Rejected: a coarser "one image-analysis port covering Quality+Classification+Authenticity" grouping — it would recreate exactly the coupling Decision 2 was frozen to eliminate (one call succeeding/failing as a unit, requiring a secondary internal protocol to recover independent stage semantics). We aren't delaying OCR because it's unimportant; we're delaying its *implementation* because its output contract hasn't been semantically frozen yet — the interface can exist now, the implementation waits.

**Decision 4 — Synchronous Document Processing Boundary. FROZEN.**

> Document processing MUST execute synchronously within `VerificationWorkflowService.submit()` while the session is in `PROCESSING`, immediately before `DecisionOrchestrator.evaluate_and_persist()` is invoked.
>
> Evidence-capture endpoints MUST remain processing-agnostic. Uploading a document, selfie, or liveness capture MUST NOT implicitly initiate the authoritative document-processing pipeline.
>
> `DocumentProcessor` MUST be idempotent and convergent across repeated `/submit` attempts. Before invoking a capability, it MUST determine whether a reusable effective `EvidenceResult` already exists for the applicable `(tenant_id, session_id, evidence_type)` stage. A reusable result MUST be reused rather than recomputed. A non-reusable result MAY be retried according to the applicable retry policy and MUST be superseded when a new attempt produces a replacement effective result. (The exact reusable-vs-retryable matrix per `EvidenceResultStatus` is carried forward as an open item, not resolved here — see §14.)
>
> Internal processing execution states required by WF-4.11/4.12 MAY exist ephemerally during a `/submit` attempt but MUST NOT require a persisted execution-state table in V1. The durable trace of stage outcome is the resulting `EvidenceResultStatus`, effective/superseded lineage, and audit events already established.
>
> Independent first-order document capabilities MAY execute concurrently because they consume the capture directly. Dependent stages MUST execute only after their required upstream EvidenceResults are available.
>
> **Implementation note (technical, not a separate decision):** "concurrent" here means each capability runs in its own `async with session_factory()` block and commits its own `EvidenceResult` independently — never multiple capabilities sharing one `AsyncSession` via `asyncio.gather()`, which SQLAlchemy does not support safely. This is not merely a technical constraint: independent per-capability transactions are the mechanism that makes partial-failure preservation (next bullet) true at the database level, not just at the application level — a shared transaction would roll back a successful stage's commit merely because a sibling stage failed inside the same transaction.
>
> Partial capability failure MUST preserve successfully produced EvidenceResults and MUST NOT cause successful stages to be discarded merely because another stage failed.
>
> Authoritative document processing MUST remain distinct from any future advisory upload-time quality or feedback capability (e.g. a client-facing "is this photo too blurry" check at capture time). Such a capability MAY be introduced later without changing the authoritative `/submit` processing boundary.
>
> Durable asynchronous processing, background workers, and persisted processing-job state remain deferred according to the existing architecture decisions (WF-4.34, TARGET v1.1).

**Decision 5 — V1 Document-Type Catalog. FROZEN.**

> PaxLI V1 MUST support the following document families, identified in `DocumentClassificationResult.document_type` by their **leaf/variant value** — `document_type` MUST use a controlled vocabulary, never an unrestricted free-form string, and carries exactly one of:
>
> - `STANDARD_NIN_SLIP` (family: `NIN_SLIP`)
> - `IMPROVED_NIN_SLIP` (family: `NIN_SLIP`)
> - `ICAO_PASSPORT_DATA_PAGE` (family: `ICAO_PASSPORT`)
>
> "Family" (`NIN_SLIP`, `ICAO_PASSPORT`) is a derived grouping/naming convention for documentation and conformance organization only — **not a second persisted field.** No downstream consumer (OCR, MRZ, field-extraction) needs family-level granularity; all extraction rules key off the specific leaf variant, so persisting both would be redundant state with its own consistency obligations for no consumer.
>
> `UNSUPPORTED` MUST NOT be represented as a document type. An unrecognized or unsupported document MUST instead produce a `DOCUMENT_CLASSIFICATION` result with `status=FAIL` and the reason code `DOCUMENT_UNSUPPORTED`.
>
> `DOCUMENT_UNSUPPORTED` MUST remain an evidence-level outcome and MUST NOT directly determine the session's final verification outcome. The Decision Engine MUST determine the final outcome according to the active policy.
>
> The V1 catalog MUST NOT imply support for document families not explicitly included in the catalog.
>
> `ICAO_PASSPORT_DATA_PAGE` MUST be modeled as an MRZ-bearing document and MUST therefore support the dedicated MRZ processing path established by the document-processing architecture.
>
> Additional document families MAY be added in future versions through explicit catalog and conformance changes.

**Decision 6 — Basic Authenticity Scope. FROZEN.**

> `DOCUMENT_AUTHENTICITY` receives no capability implementation in Phase 1 through Phase 4 of the V1 document-processing vertical slice. `AuthenticityChecker`'s port exists per Decision 3 but is not implemented.
>
> When a policy does not require `DOCUMENT_AUTHENTICITY`, it resolves to `NOT_REQUIRED`. When a policy requires it, the evidence stage resolves to `status = UNAVAILABLE` with reason code `AUTHENTICITY_CAPABILITY_UNAVAILABLE` — this is the evidence producer honestly reporting what it does not know. The Decision Engine, not the evidence stage, determines the session-level consequence (`REVIEW_REQUIRED`/`INCONCLUSIVE`/etc.) according to the active policy. `DOCUMENT_AUTHENTICITY` MUST NOT resolve to `PASS` by default or by omission.
>
> MRZ check-digit validation is NOT a `DOCUMENT_AUTHENTICITY` signal. A failing MRZ checksum is represented as `MRZ = FAIL` on the `MRZ` evidence type itself — a valid checksum establishes structural/data validity of the MRZ, not that the underlying document is genuine.
>
> Reused-image/duplicate-submission detection ("have we seen this artifact before?") is explicitly out of scope for `DOCUMENT_AUTHENTICITY` ("is this document genuine?") — a different question, and a separate, not-yet-designed capability if pursued.
>
> A genuine authenticity capability requires its own dedicated discovery, per DEF-9.15.3's conformance-assessment requirement, once a real signal beyond deferred territory (Part IX §9.15: chip/NFC, cryptographic, tamper, issuer-specific, expanded document families) is identified.

**Architectural finding, not an implementation gap:** V1 does not implement document authenticity because the available V1 inputs (a 2D image, no physical sensor, two document families) do not provide a defensible authenticity signal outside the capabilities Part IX explicitly defers — not because it was overlooked. PaxLI can verify identity *evidence* (quality, classification, OCR/MRZ/barcode extraction, canonical field consistency, cross-evidence consistency, policy-driven decisioning, auditable provenance) without claiming to establish document *authenticity*; these are different capabilities, and the commercially dangerous move would be implying the former proves the latter.

**Decision 7 — `DOCUMENT_FIELD_EXTRACTION` Schema Shape. FROZEN.**

> `DOCUMENT_FIELD_EXTRACTION` uses a hybrid schema: controlled canonical top-level fields plus an opaque document-specific `extensions` map. Canonical fields: `full_name`, `surname`, `given_names`, `date_of_birth`, `sex`, `document_number`, `nationality`, `expiry_date`. Canonical fields not applicable to a document type, or whose decomposition cannot be reliably established from the source, are `null` rather than omitted or empty-stringed. `extensions: dict[str, str]` preserves document-specific fields outside the canonical vocabulary and is NOT directly addressable by Decision Engine policy conditions in V1 — no JSON-path-style traversal into it.
>
> `full_name` represents the canonical normalized whole-name value. `surname`/`given_names` represent independently supported name components and remain nullable where the source document doesn't provide a trustworthy decomposition. They are not required to reconstruct `full_name` for every document type.
>
> `document_number` is the canonical semantic slot for a document's primary identifying number (NIN for `NIN_SLIP`, passport number for `ICAO_PASSPORT_DATA_PAGE`), not a name specific to any one document type.
>
> When both `full_name` and `surname`/`given_names` are populated for the same result, the (still-unresolved) reconciliation algorithm MUST derive them consistently from the same normalization pass — they must not be independently reconciled and left free to diverge.
>
> `OCR_EXTRACTION`, `MRZ`, and `BARCODE_QR` retain their source-specific, non-canonical extraction representations — this decision governs only `DOCUMENT_FIELD_EXTRACTION`'s reconciled output. The cross-source reconciliation algorithm (normalization, conflict resolution, name-component derivation) remains a separate, unresolved architectural item.

Rejected: narrowing the canonical list to 4 fields (deferring `sex`/`nationality`/`expiry_date` to `extensions` until a third document type demonstrated need). "Canonical" doesn't mean "every document type must contain this field" — it means "when a supported document expresses this semantic attribute, it has a standardized place in the reconciled representation." The two already-frozen document families (Decision 5) already demonstrate the need for all eight fields; waiting for a hypothetical third type would gain nothing. Also rejected: dropping `full_name` as "redundant" with `surname`/`given_names` — that reasoning (valid for Decision 5's family/variant question) doesn't transfer here, because `full_name` is NOT always derivable from the other two: for `NIN_SLIP`, where decomposition isn't trustworthy, `full_name` is the only available canonical name representation.

---

## 17. Proposed implementation phases

**Phase 0 (this document).** Discovery and reconciliation. No code.

**Phase 1 — Deterministic vertical slice (FROZEN scope, per Decisions 3 and 4).** All six capability ports interface-designed; only `QualityAssessor` and `DocumentClassifier` get deterministic implementations. `DocumentProcessor` orchestration wired into `VerificationWorkflowService.submit()`'s `PROCESSING` branch, immediately before `evaluate_and_persist()`, per Decision 4 — capture endpoints stay unmodified. Real `EvidenceResult` rows (`DOCUMENT_QUALITY`, `DOCUMENT_CLASSIFICATION`) with real lineage (`source_reference`), real policy evaluation against them — end to end, but with deterministic (not ML) outputs, and no OCR-shaped schema blessed prematurely. This directly closes the "generic mechanism test only" gap the repo inventory found for every document type, for these two.

**Phase 2 — Field-schema and document-catalog decisions land** (Decisions 5 and 7, both now frozen), unblocking `OCREngine`/`MRZParser`/`BarcodeDecoder` implementations. Deterministic implementations for all three, plus `DOCUMENT_FIELD_EXTRACTION` reconciliation across their outputs (`parent_evidence_result_ids` spanning OCR/MRZ/barcode per Decision 2) — the reconciliation *algorithm* itself (normalization, conflict resolution, name-component derivation) is designed in this phase, not before.

**Phase 3 — Real adapter for at least one capability** (most likely OCR, as the highest-value real signal), behind the same port, validated against the deterministic baseline's contract.

**Phase 4 — `IdentityConsistency`**, once Open Question 5 (its inputs/algorithm) is settled. `DocumentAuthenticity` is explicitly NOT implemented in this phase or any phase of this vertical slice, per Decision 6 — it remains an unimplemented capability pending a dedicated future discovery once a real signal beyond deferred territory exists.

Each phase gets its own hostile-validation pass once built, following the exact HV-XXX discipline this session established — not bundled into one giant HV-010.

---

## 18. Conformance/test strategy

Per EVD-3.32 and CONF-8.9/8.12, and matching this project's existing test-layer convention:
- `tests/unit/` — schema validation for real (not placeholder) per-type payloads once schemas are enriched; condition-evaluation tests referencing real document fields.
- `tests/integration/` — real-Postgres `EvidenceResultService.create()` round-trips for every document type with a *real-shaped* payload (not `{"fields": {"name": "CANARY_NAME"}}`); full orchestration-to-decision tests mirroring `test_decision_orchestration.py`'s existing pattern but with document evidence driving the outcome.
- `tests/contracts/` — the normative EVD-3.x/DEC-5.x requirements this pipeline newly makes reachable (currently these exist as spec text with no implementation to test against; per CONF-8.9.2/REL-10.21, once real, they need genuine failure-injection tests: model-unavailable, malformed-output, timeout).
- A dedicated hostile-validation phase (HV-010, once Phase 1 lands) attacking exactly the failure modes enumerated in §11 that the current HV-009 campaign couldn't reach because nothing produced document evidence yet.

---

## Appendix — raw discovery source

The full requirement-by-requirement spec trace (every EVD-3.x/WF-4.x/DEC-5.x/SEC-7.x/CONF-8.x/DEF-9.x/REL-10.x/PRV-11.x citation with quoted text) and the full repository inventory (every enum member's reference count, full schema source, full provider-ABC source, full grep results) that this document synthesizes are available in this session's transcript and can be re-run or expanded on request — they were deliberately not reproduced in full here to keep this record navigable, per its own stated purpose as a reconciliation document rather than a raw research dump.
