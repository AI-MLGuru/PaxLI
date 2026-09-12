# DP-001 — Document Processing Discovery & Reconciliation

**Status:** DISCOVERY — no production code changed. Awaiting peer-review/reconciliation before any implementation is authorized.
**Scope:** the first real document-processing pipeline (quality, classification, OCR, MRZ, barcode/QR, authenticity) as the first genuine producer of `EvidenceResult` rows.
**Method:** full trace of `docs/specification/part-03` through `part-11` for every document-relevant requirement, plus a full repository inventory of `core/`, `infrastructure/`, `integrations/`, `apps/`, `tests/`, and prior foundation/decision records. Citations below are `file:line`.

---

## 1. Scope

In scope for this discovery: everything needed to take a raw `DOCUMENT` capture (`core/evidence/`) through quality/classification/OCR/MRZ/barcode/authenticity processing into `EvidenceResult` rows (`core/evidence_result/`) that the existing, already-hardened Decision Engine can evaluate — without modifying session-lifecycle semantics, Decision Engine semantics, or any of the WF-002–HV-009 frozen contracts.

Out of scope for this discovery (and therefore not addressed below beyond noting where they intersect): the Face and Liveness pipelines (same architectural shape, deliberately deferred to their own discovery once the Document slice proves the pattern), and any real ML model selection/training.

---

## 2. The headline finding — a genuine spec/implementation conflict

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

**Recommendation, not yet a decision:** this should be **several typed `EvidenceResult` rows, not one composite result** — each with `source_reference` pointing at the capture and `parent_evidence_result_ids` pointing at its upstream stage(s) where derivation is genuine (e.g., `DOCUMENT_FIELD_EXTRACTION` derived from both `OCR_EXTRACTION` and `MRZ`). This is directly supported by:
- EVD-3.17's own lineage language ("derived evidence must identify source evidence")
- REL-10.15 (partial pipeline failure must preserve completed evidence) — a single composite row would make "OCR succeeded, MRZ failed" inexpressible without either a partially-null mega-object or two competing writes to one row (which immutability forbids anyway)
- The existing schema catalog's one-schema-per-type design, which a composite result would have to abandon or awkwardly nest

This is Explicit Decision #2 in §16.

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

**Recommendation:** Option C, sequenced so the deterministic baseline (a) proves the orchestration/lineage/schema design decisions in §6–8, then (b) a real adapter is slotted in behind the same port once those decisions are validated and a specific document type / OCR library is chosen. This is Explicit Decision #3.

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

1. **Where does synchronous document processing actually run?** `submit()`'s `PROCESSING` branch calls `evaluate_and_persist()` directly today. Does document processing happen inside `submit()` before that call (making `/submit` itself slower and subject to inference timeouts), or does it happen at evidence-submission time (`POST /document` triggers processing immediately, before the client ever calls `/submit`)? These have materially different latency, retry, and idempotency consequences and are not decided anywhere in the existing lifecycle design.
2. **Where is the "basic vs advanced" document authenticity line?** DEF-9.15 defers "advanced" checks but implies a baseline exists for v1.0. What does baseline authenticity actually check, concretely, with today's ambition (format/template matching? nothing at all, `NOT_REQUIRED` until a real signal exists)?
3. **Where do evidence-level reason codes (Part III §3.14: `OCR_UNREADABLE`, `DOCUMENT_UNSUPPORTED`, etc.) live in code?** No such enum exists today — `EngineReasonCode` is decision-level only. This needs a home (likely `core/evidence_result/reason_codes.py`, mirroring `core/policy/reason_codes.py`'s `POLICY:` namespace pattern) before any component can honestly report `IMAGE_TOO_BLURRY`.
4. **Is there a document-type catalog for v1.0, and if so what's in it?** The spec never names one. Recommend defining a short, explicit list (e.g., passport + one national ID format) rather than trying to build a general document-family classifier immediately — but this is your call, not mine to assume.
5. **What does `IDENTITY_CONSISTENCY` actually check?** No section defines its inputs or algorithm. Exact-match on OCR'd name vs. session-provided name? Fuzzy match? DOB tolerance? Cross-check against `ExternalIdentityProvider` when that's eventually built?
6. **Should `DocumentFieldExtractionResult` stay a nested `dict[str, str]`, or become a flatter, per-identity-attribute schema?** Blocks or unblocks field-level policy conditions (§8). A nested dict is more flexible for unknown document layouts; a flat schema is more policy-expressive. This also interacts with Open Question 4 (a document-type catalog would let per-type field schemas exist).
7. **One composite `EvidenceResult` vs. several typed rows per pipeline run (§6)?** Recommended: several, but this is Explicit Decision #2, not yet settled.

---

## 15. Recommended implementation shape

```
DocumentProcessor (orchestration, core/document/)
        │
        ▼
┌───────────────────────────┐
│   Capability Ports         │   (interfaces only, core/document/)
├───────────────────────────┤
│ QualityAssessor             │
│ DocumentClassifier          │
│ OCREngine                   │
│ MRZParser                   │
│ BarcodeDecoder               │
│ AuthenticityChecker (basic)  │
└──────────────┬────────────┘
               │
     ┌─────────┴─────────┐
     ▼                   ▼
Deterministic         Real adapter
baseline (Phase 1)    (Phase 2+, behind
                       infrastructure/reliability's
                       guarded_infer() wrapper)
               │
               ▼
     EvidenceResultService.create()  (existing, unmodified)
               │
               ▼
     Decision Engine  (existing, unmodified)
```

This is Option C from §9, matches the existing `DocumentProvider` ABC's intent, requires zero changes to `EvidenceResultService`, `DecisionOrchestrator`, or any WF/DE/HV-frozen contract, and lets Phase 1 validate every open architectural question in §14 against a deterministic, fully-controllable stub before any real library or model is chosen.

---

## 16. Explicit decisions requiring your approval

**Decision 1 — Document `EvidenceResultType` classification.** Recommend reclassifying `DOCUMENT_QUALITY, DOCUMENT_CLASSIFICATION, OCR_EXTRACTION, DOCUMENT_FIELD_EXTRACTION, MRZ, BARCODE_QR, DOCUMENT_AUTHENTICITY` from `SENSITIVE` to `HIGHLY_SENSITIVE` in `core/evidence_result/classification.py`, matching Part XI §11.7's explicit language, before any real document content flows through the pipeline. `IDENTITY_CONSISTENCY` and `EXTERNAL_IDENTITY_PROVIDER` can plausibly stay `SENSITIVE` (they hold comparison/match outcomes, not raw extracted document content) — worth confirming per-type rather than blanket. This is a spec-conformance fix, not a design choice, but I'm not making it unilaterally per CLAUDE.md's conflict-resolution rule, and it wasn't part of this discovery's "no code changes" scope anyway.

**Decision 2 — Composite vs. several `EvidenceResult` rows per pipeline run.** Recommend several typed rows with explicit lineage (§6), against a single composite result.

**Decision 3 — Inference boundary shape.** Recommend Option C (capability ports + deterministic baseline first, real adapter later), per §9's comparative analysis.

**Decision 4 — Where synchronous processing runs in the request lifecycle** (Open Question 1) — needs your call; this shapes `/submit`'s latency profile and whether `/document` upload itself becomes a slower call.

**Decision 5 — Document-type catalog scope for v1.0** (Open Question 4) — needs an explicit, named list rather than an open-ended classifier target.

**Decision 6 — Basic authenticity scope** (Open Question 2) — needs a concrete, minimal definition or an explicit "not built yet, reports NOT_REQUIRED" decision for Phase 1.

---

## 17. Proposed implementation phases

**Phase 0 (this document).** Discovery and reconciliation. No code.

**Phase 1 — Deterministic vertical slice.** Capability ports + deterministic stub implementations for `DocumentQuality`, `DocumentClassification`, `OCRExtraction` only (the two types with at least placeholder precedent, plus classification as the natural next step). `DocumentProcessor` orchestration wired into wherever Decision 4 lands. Real `EvidenceResult` rows, real lineage (`source_reference`/`parent_evidence_result_ids`), real policy evaluation against them — end to end, but with deterministic (not ML) outputs. This directly closes the "generic mechanism test only" gap the repo inventory found for every document type.

**Phase 2 — MRZ + Barcode/QR.** Add the two remaining, currently zero-coverage evidence types, with the field-reconciliation question (Open Question 6) resolved by this point since `DOCUMENT_FIELD_EXTRACTION` needs OCR+MRZ+barcode inputs.

**Phase 3 — Real adapter for at least one capability** (most likely OCR, as the highest-value real signal), behind the same port, validated against the deterministic baseline's contract.

**Phase 4 — Basic `DocumentAuthenticity` and `IdentityConsistency`**, once Decisions 5/6 and Open Question 5 are settled.

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
