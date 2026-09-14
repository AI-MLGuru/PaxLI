# BD-001 — Biometric Demo Implementation Plan

**Status:** FROZEN — reconciled across two passes (initial 8-point
architectural review; final confirmation of quality-gating, liveness
protocol, `FaceMatch` status mapping, synchronous processing, and
frontend framework). All ten items in the consolidated decision
summary are resolved — eight FROZEN, two (PaddleOCR's exact model,
InsightFace's internal session topology) deliberately classified as
implementation-time freedoms rather than open architecture. No
production code has been written — this freeze authorizes
implementation to begin against a plan with no remaining undecided
architecture, not the implementation itself.

**Naming note:** new series (`BD-`, Biometric Demo), distinct from
`DP-`/`BP-`/`TD-`. It isn't `BP-002` — `BP-002` is PaxLI's real
production implementation plan and stays gated on BP-001's still-open
§6c provider questions. This plan implements only the technical demo,
against BP-001.5's already-frozen architecture and TD-001's already-
frozen technology choice.

**Inputs, all already FROZEN and treated as fixed constraints here, not
reopened:**
- BP-001 (§1-§12): capability boundaries, `FaceMatch` semantics,
  reference-source routing, derived-evidence freshness, orchestration
  discipline.
- BP-001.5 (Decisions 18-22): `ReferenceIdentity` shape, the two
  compatibility checks, `FaceMatch` lineage/status semantics, the
  eager/inline/symmetric orchestration trigger model.
- TD-001: InsightFace `buffalo_l` (detection+recognition only), ONNX
  Runtime CPU, 512-D embeddings, cosine similarity, no explicit thread
  tuning.
- DP-001 through DP-010 (closed): the document-processing pattern this
  plan reuses — `capabilities.py` ports, `CapabilityUnavailableError`,
  `_persist_stage`/`_is_reusable`, `DocumentFieldReconciler`'s
  non-port precedent.

**Grounding for this pass:** `core/document/types.py`,
`core/verification/workflow.py`, `apps/api/paxli_api/routers/evidence.py`
were read directly for this draft — the capture endpoints
(`/selfie`, `/document`, `/liveness`) and `VerificationWorkflowService.submit()`'s
exact structure are current-code facts, not assumptions.

---

## Slice A — `PaddleOCREngine`

Implements the already-frozen `core.document.capabilities.OCREngine`
port unchanged:

```python
class PaddleOCREngine(OCREngine):
    async def extract(self, image: bytes) -> OCRReadResult: ...
```

PaddleOCR's own response shape (its list-of-boxes/text/confidence
structure) is translated inside this adapter into `OCRReadResult`/
`OCRExtraction` (`raw: str`, `fields: dict[str, str]`) — never leaked
upstream, per your explicit instruction. `outcome=UNREADABLE` when
PaddleOCR returns no usable text; `VALID` otherwise (DP-005 Decision 3:
OCR has no capability-level absence state, matches the existing
contract exactly). Swaps in behind `DeterministicOCREngine` at exactly
one call site (`apps/api/paxli_api/dependencies.py:221`) — no other
file changes required for this slice alone. `paddleocr`/`paddlepaddle`
become new `pyproject.toml` dependencies (Apache 2.0, already cleared
by TD-001's research — no further licensing question here).

**Classified as implementation-time technology selection, not an open
architectural decision — this plan does not need to know the exact
model to be freezable.** PaddleOCR's model lineup has changed
considerably across releases; "v4/v5 mobile" is not a stable enough
reference to freeze into an implementation plan. The frozen process,
mirroring TD-001's own discipline exactly:

```text
Install the current approved PaddleOCR stack
        |
        v
Inspect available English OCR models
        |
        v
Select ONE candidate
        |
        v
Benchmark on representative document samples
        |
        v
Record the exact package/model/version
        |
        v
Implement the adapter
```

---

## Slice B — Face detection: a new `core/face/capabilities.py`

`core/face/provider.py`'s `FaceProvider` stays rejected (BP-001 Decision
2). This slice creates the actual replacement, mirroring
`core/document/capabilities.py`'s pattern exactly (same file
docstring convention, same `CapabilityUnavailableError`, same
`image: bytes -> domain result` async shape — BP-001 §7's own
prediction confirmed as a clean fit):

```python
# core/face/types.py (new) -- domain results, mirrors core/document/types.py
@dataclass(frozen=True)
class FaceDetection:
    detected: bool
    face_count: int
    # bounding box(es)/landmarks: demo-internal only, NOT persisted into
    # FaceDetectionResult's frozen schema (core/evidence_result/schemas.py
    # already fixes that shape at detected: bool, face_count: int | None --
    # this slice does not reopen that schema)

# core/face/capabilities.py (new)
class FaceDetector(ABC):
    @abstractmethod
    async def detect(self, image: bytes) -> FaceDetection: ...
```

```python
# infrastructure/face/insightface_adapter.py (new)
class InsightFaceDetector(FaceDetector):
    """TD-001's buffalo_l, detection module. MUST be backed by a
    long-lived runtime instance, never constructed per-request -- model
    load is expensive (TD-001 measured 6-18s depending on
    configuration). **Not frozen here**: whether detection and
    recognition share one `FaceAnalysis` instance, use two separate
    instances, or something else. TD-001 froze which modules run
    (detection+recognition, default threading) -- it explicitly did
    NOT freeze internal session topology, and this plan doesn't either.
    TD-001's own benchmark is the reason: the restricted-module
    configuration measured *worse*, not better, than default in one
    test, which is exactly the kind of counter-intuitive result that
    means this must be settled by measurement at implementation time,
    not assumed here."""
```

`CapabilityUnavailableError` fires on a genuine InsightFace/ONNX Runtime
failure (model load error, corrupt image the decoder rejects) — never
on "zero faces found," which is a legitimate `FaceDetection(detected=False,
face_count=0)` result, confirmed by this session's own benchmark (random
noise/blank images returned `[]` with no exception).

---

## Slice C — Face quality: the decision this plan must NOT silently make

```python
class FaceQualityAssessor(ABC):
    @abstractmethod
    async def assess(self, image: bytes) -> FaceQuality: ...  # FaceQuality: quality_score: float
```

Implementation proposal (demo-only, not a production quality model):
composite of blur (Laplacian variance via OpenCV, already a Slice B
dependency), brightness/exposure, and InsightFace's own detection
confidence (`det_score`) for the primary face. This is a heuristic
stand-in — same spirit as `DeterministicQualityAssessor` on the document
side, not a claim of production-grade face quality science.

> **FROZEN.** `FaceQualityAssessor` never decides "too poor, don't
> embed" — that would be an orchestration/policy judgment leaking into
> a capability, the same "evidence is not a verdict" boundary BP-001
> §9.4 already draws for cardinality. For the demo specifically:
> **`BiometricProcessor` always attempts embedding when a face
> candidate exists, regardless of `FaceQuality`'s score.** `FaceQuality`
> is persisted as its own independent `FACE_QUALITY` evidence row
> alongside `FACE_EMBEDDING`, not consulted as a precondition. This is
> deliberate for a *demo*: it lets the pipeline surface real
> `quality=poor, embedding=succeeded, similarity=X` observations instead
> of hiding them behind an unvalidated threshold guess — exactly the
> kind of evidence a later, real threshold-calibration exercise would
> need. This does not resolve BP-001 §9.4/§9.5 for production — a
> future production policy remains free to gate on `FaceQuality` via
> the Decision Engine (a `BLOCKING` gate against `FaceQuality.quality_score`,
> zero new mechanism needed) without touching `FaceEmbedder` at all,
> which is exactly why keeping the capabilities decoupled here matters.

---

## Slice D — `InsightFaceEmbedder`

```python
class FaceEmbedder(ABC):
    @abstractmethod
    async def embed(self, image: bytes) -> FaceEmbedding: ...  # embedding: tuple[float,...], dimensions: int
```

`InsightFaceEmbedder` wraps `buffalo_l`'s recognition module
(`w600k_r50`), returns the 512-D L2-normalized vector TD-001 already
confirmed. The `EvidenceResult.model_reference` this produces:

```python
ModelReference(
    model_id="insightface/buffalo_l/w600k_r50",
    model_version="buffalo_l",  # InsightFace's own pack versioning is
                                 # coarse -- exact per-file hash/version
                                 # pinning is implementation detail, not
                                 # frozen here
    runtime="onnxruntime",
    runtime_version=<captured from `onnxruntime.__version__` at startup>,
)
```

This is what BP-001.5 Decision 19's `FaceMatcher`-level compatibility
check (Slice E) actually compares — confirmed to be the right field,
not a new one, since `ModelReference` already exists generically
(`core/evidence_result/models.py:13-18`).

---

## Slice E — `FaceMatcher`

Per BP-001.5 Decisions 8/19/20/21, implemented exactly as frozen —
this slice is pure application of already-made decisions, no new ones:

```python
# core/face/matcher.py (new, NOT in capabilities.py -- BP Decision 8)
class FaceMatcher(ABC):
    @abstractmethod
    def compare(self, *, reference: FaceEmbedding, probe: FaceEmbedding) -> FaceMatchOutcome: ...
```

```python
@dataclass(frozen=True)
class FaceMatchOutcome:
    similarity: float | None  # None exactly when incompatible (below)
    compatible: bool
```

`DeterministicFaceMatcher` (or `CosineFaceMatcher` — naming TBD, not
frozen): computes cosine similarity when `reference.model_reference ==
probe.model_reference` (BP-001.5 Decision 19 point 2); when they
differ, `compatible=False`, `similarity=None` — never a fabricated
number. `infrastructure/face/processor.py` (Slice G) is what maps this
onto `FaceMatchResult(similarity, reference_evidence_result_id,
probe_evidence_result_id)` and an `EvidenceResultStatus` — per BP-001.5
Decision 21, `PASS` when `compatible`, and the exact status/reason code
for `compatible=False` is **explicitly still open per BP-001.5's own
Decision 21 split** (principle frozen, mapping deferred to this plan).

**FROZEN — revised, replacing the earlier `UNAVAILABLE` mapping.**
`UNAVAILABLE` was wrong and is withdrawn, not merely refined.
`UNAVAILABLE` means something specific and different everywhere else
this project uses it: a required provider/resource could not be
reached (`CapabilityUnavailableError`'s own domain — model load
failure, timeout, a recognized infrastructure fault). A model-version
mismatch between reference and probe is none of that — `FaceMatcher`
**is** available and **did** execute; it correctly determined the
comparison as posed cannot yield a meaningful result. Searching the
existing taxonomy rather than inventing one: this is structurally the
same shape as `DOCUMENT_FIELD_EXTRACTION`'s own precedent (DP-008 §3.5,
Phase 4) — sources present and individually readable, but disagreeing
in a way that makes a single safe value unproducible, mapped to
`status=INCONCLUSIVE`, never `UNAVAILABLE` or `FAIL`. The parallel
holds here: both representations are present and individually valid;
they just can't be safely compared together. `status=INCONCLUSIVE`,
with a new reason code following `core/document/reason_codes.py`'s own
established convention (bare name, no invented namespace prefix — that
question is explicitly still open project-wide, per that module's own
docstring, and this plan doesn't resolve it either): a new
`core/face/reason_codes.py` with `REPRESENTATION_INCOMPATIBLE`.

**Precise meaning, frozen alongside the code itself, not left to
inference:** `REPRESENTATION_INCOMPATIBLE` means *the two
representations cannot safely be compared* — a statement about the
comparison operation's own precondition, never a claim that either
representation is itself invalid or low-quality (that's `FaceQuality`'s
domain, an entirely separate evidence row). Correspondingly, `FAIL`
stays reserved for a genuine future negative-comparison outcome — a
capability-level determination made only once the matcher already has
two *compatible* representations and something about the comparison
itself is negative (no such condition exists in this plan's scope; the
demo's `FaceMatcher` only ever produces `PASS` or this `INCONCLUSIVE`
refusal, never `FAIL` — recorded so a future implementer doesn't
invent a `FAIL` path this plan never designed).

---

## Slice F — Liveness: the second decision this plan must NOT silently make

**Current, confirmed fact:** `POST /{session_id}/liveness`
(`apps/api/paxli_api/routers/evidence.py:184-209`) accepts exactly one
`UploadFile`, identical in shape to `/selfie` and `/document`. BP-001
§2's finding — the capture layer cannot deliver `LivenessProvider`'s
`frames: list[bytes]` — is confirmed still true today, not stale.

> **FROZEN: (i), bounded multi-file upload.** `/liveness` is extended to
> accept `frames: list[UploadFile]`, bounded to a small fixed demo range
> (proposed default: 5 frames — the exact bound is implementation-time
> tuning, not a reopening of the protocol choice itself). Rejected
> alternatives, for the record: **(ii) short video upload** — a new
> `infrastructure` dependency (ffmpeg or an OpenCV video decoder) for no
> benefit the demo actually needs; **(iii) a dedicated sequence-capture
> endpoint** — more capture-layer surface than justified when a bounded
> multi-file extension of the existing `/liveness` endpoint gives the
> same temporal signal. The frontend (Slice L) is free to present this
> as a live, guided capture sequence (frame-by-frame progress) even
> though the backend receives one bounded batch — the capture
> *experience* and the capture *protocol* are separate concerns.

**Equally important, and explicit per your instruction:** whatever the
demo's `LivenessAssessor` computes, it MUST NOT be described or logged
as "detects a face in successive frames, therefore live." Proposed demo
heuristic (a labeled demonstrator, not real PAD): inter-frame landmark
displacement (eye/mouth landmark movement across frames, using
InsightFace's own 2D landmarks) as a weak liveness signal, explicitly
distinct from a real challenge-response/texture/replay-detection PAD
system. `LivenessAssessmentResult(live_score, attack_score)`'s existing
schema already fits this without change — the schema was never the gap,
the capture boundary and the honest labeling were.

**Non-goal, restated from BP-001 §9.1/§10:** this is not "liveness
enters V1 scope." It is a clearly-labeled demo capability, kept fully
separable — the demo's Decision Engine policy can require it or not,
independent of whether real PAD ever ships.

**Terminology is part of the frozen contract, not a documentation
nicety.** Every surface this reaches — API field/label names, log
event names, frontend copy — MUST call this "Liveness Heuristic Demo"
or "Temporal Liveness Demo," never plain "Liveness" or "Liveness
Check" unqualified. Frame-to-frame landmark movement is weak enough
that a replayed video would pass it — presenting it as if it were
production-grade PAD would misrepresent what was actually built, the
same discipline this project applies to `DeterministicOCREngine`/
`DeterministicQualityAssessor` never being described as production
models.

---

## Slice G — Reference acquisition and cross-capture orchestration

**Corrected from the first draft: `DocumentFaceExtractor` does NOT live
inside `BiometricProcessor`.** The first draft implied
`BiometricProcessor` would know how to acquire a reference, which is
exactly the coupling BP-001.5 Decision 18 forbids (`FaceMatcher`, and
by extension the biometric pipeline generally, "MUST NOT know...
whether a representation it receives came from a document scan, a NIN
Data Print, an external provider"). The corrected boundary:

```text
Document capture
      |
      +-- DocumentProcessor (existing, unchanged)
      |       Quality / Classification / OCR / MRZ / Barcode /
      |       Field reconciliation
      |
      `-- ReferenceSourceResolver (new)
              |
              `-- DocumentBoundReferenceResolver (demo's only
                  implementation -- route (A) only, per BP-001 §6b;
                  (A')/(B) stay out of scope, gated by §6c)
                      |
                      `-- DocumentFaceExtractor (new capability,
                          used BY the resolver, not by BiometricProcessor)
                              |
                              v
                        ReferenceIdentity | AcquisitionOutcome
                              |
                              v
                        BiometricProcessor (consumes ReferenceIdentity;
                        never knows or asks how it was produced)
```

```python
# core/face/reference.py (new)
class ReferenceSourceResolver(ABC):
    @abstractmethod
    async def resolve(self, *, session_id: UUID, tenant_id: str) -> ReferenceResolution: ...

@dataclass(frozen=True)
class ReferenceResolution:
    """Always populated, never a bare Optional -- mirrors OCRReadResult/
    MRZReadResult's own outcome+payload pattern (core/document/types.py)
    rather than collapsing distinguishable outcomes into None."""
    outcome: ReferenceAcquisitionOutcome
    identity: ReferenceIdentity | None  # populated iff outcome=RESOLVED

class ReferenceAcquisitionOutcome(StrEnum):
    NOT_AVAILABLE = "NOT_AVAILABLE"    # no DOCUMENT capture, or upstream
                                        # document processing hasn't
                                        # produced a usable classification/
                                        # field-extraction result yet
    NO_FACE_FOUND = "NO_FACE_FOUND"    # document image had zero
                                        # detectable faces
    AMBIGUOUS = "AMBIGUOUS"            # more than one face candidate --
                                        # see the selection rule below;
                                        # never silently resolved
    RESOLVED = "RESOLVED"
```

**Dependency-inversion statement, made explicit rather than left
implicit:**

```python
reference_source: ReferenceSourceResolver   # the abstract dependency
                                             # BiometricProcessor holds
```

wired, at the composition root only, as:

```python
ReferenceSourceResolver = DocumentBoundReferenceResolver(...)   # the
                                                                  # demo's
                                                                  # only
                                                                  # implementation
```

`BiometricProcessor` calls `resolve()` once per attempt and only
proceeds down the reference-side sub-chain on `RESOLVED` — it has no
knowledge that `DocumentBoundReferenceResolver` is the concrete class
behind that interface, cannot introspect route (A) specifically, and
would require zero change the day a `NINDataPrintReferenceResolver`
(route (A')) or a composed multi-route resolver exists.
`NOT_AVAILABLE`/`NO_FACE_FOUND`/`AMBIGUOUS` all mean "no reference-side
rows produced this attempt" (not an error; same "no row until ready"
principle BP-001.5 §5 already established for the *match* attempt, now
applied one layer earlier, to reference *acquisition* itself). Whether
`AMBIGUOUS` should itself become a persisted, reason-coded evidence
signal (so a human reviewer can see *why* no reference was ever
acquired) rather than a silent no-op is worth deciding at
implementation time — flagged, not resolved here.

**`DocumentFaceExtractor` — explicit, documented candidate-selection
rule, never an implicit "pick the largest face":**

```python
class DocumentFaceExtractor(ABC):
    @abstractmethod
    async def extract_candidate(self, image: bytes) -> DocumentFaceCandidate: ...

@dataclass(frozen=True)
class DocumentFaceCandidate:
    outcome: Literal["NO_FACE", "SINGLE_CANDIDATE", "AMBIGUOUS_MULTIPLE_FACES"]
    region: FaceRegion | None  # populated iff outcome == "SINGLE_CANDIDATE"
```

The rule, stated explicitly per your instruction: **zero faces →
`NO_FACE`; exactly one face → `SINGLE_CANDIDATE`; more than one →
`AMBIGUOUS_MULTIPLE_FACES`, full stop — no largest-face, most-central,
or highest-confidence tiebreak.** A document photo region is not
guaranteed to be the only face a detector finds in a complex document
layout (a watermark, a second printed photo, a signature panel
misdetected as a face) — silently picking one would manufacture an
identity claim `DocumentFaceExtractor` has no basis to make.
`ReferenceSourceResolver` maps `AMBIGUOUS_MULTIPLE_FACES` straight to
`ReferenceAcquisitionOutcome.AMBIGUOUS` above.

Demo implementation of `DocumentFaceExtractor` reuses `InsightFaceDetector`'s
own detection (crop whichever single bounding box exists in the
`SINGLE_CANDIDATE` case) rather than building a second detector — the
document photo and a selfie are both "a face in an image" at that
capability's level; `ReferenceIdentity` is exactly what makes this
reuse legitimate rather than a layering violation.

---

## Slice G.2 — `BiometricProcessor`

Implements BP-001.5 Decision 22, now correctly scoped to *only* the
biometric pipeline (reference and probe sub-chains, `FaceMatch`
attempt) — reference *acquisition* is Slice G's `ReferenceSourceResolver`,
consumed here, not performed here:

```python
# infrastructure/face/processor.py (new)
class BiometricProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        key_provider: KeyProvider,
        key_id: str,
        face_detector: FaceDetector,
        face_quality_assessor: FaceQualityAssessor,
        face_embedder: FaceEmbedder,
        face_matcher: FaceMatcher,
        reference_source: ReferenceSourceResolver,
        liveness_assessor: LivenessAssessor | None,  # None = demo liveness disabled
    ) -> None: ...

    async def process(self, *, session_id: UUID, tenant_id: str,
                       request_id: str | None, correlation_id: str | None) -> None:
        """Mirrors DocumentProcessor.process()'s own shape: independent
        per-stage sessions, `_is_reusable`/`_persist_stage`-style
        create/supersede branching (BP-001.5 §6, "primitives transfer,
        shape does not"). Calls reference_source.resolve() once; on
        RESOLVED, runs the reference-side sub-chain (detect/quality/
        embed on the resolved ReferenceIdentity's artifact -- detect/
        quality are skipped entirely if the artifact is already an
        Embedding, per BP-001.5 Decision 18's tagged union). Runs the
        probe-side sub-chain unconditionally if a SELFIE capture
        exists. Attempts FaceMatch per BP-001.5 Decision 22's
        completion-triggered model: no FACE_MATCH row until both sides
        have a reusable effective FACE_EMBEDDING."""
```

**`process()` is called from `VerificationWorkflowService`, not
scheduled independently** — see Slice I.

---

## Slice H — Evidence persistence/lineage

Direct application of BP-001.5 §3a/§4/Decision 10 — no new decisions,
only wiring:

- `FACE_DETECTION`/`FACE_QUALITY`/`FACE_EMBEDDING` rows use the same
  `create()`/`supersede()` + `parent_evidence_result_ids` pattern
  `SqlAlchemyDocumentProcessor` already proves, per stage, per side
  (reference/probe independently).
- `FACE_MATCH` rows: `parent_evidence_result_ids=(ref_embedding.id,
  probe_embedding.id)`, plus `FaceMatchResult.reference_evidence_result_id`/
  `probe_evidence_result_id` (BP-001.5 Decision 20's domain invariant
  enforced in a `FaceMatchResult.__post_init__`, mirroring
  `FieldReconciliationResult`'s own precedent exactly).
- Classification: `FACE_EMBEDDING` stays `HIGHLY_SENSITIVE`,
  `FACE_DETECTION`/`FACE_QUALITY`/`FACE_MATCH` stay `SENSITIVE` — already
  correct in `core/evidence_result/classification.py`, zero change
  needed (BP-001 §4, reconfirmed).

---

## Slice I — `VerificationWorkflowService` integration

Exact, minimal change to the real, current file
(`core/verification/workflow.py:57-145`):

```python
def __init__(self, session_service, decision_orchestrator, audit_service,
             document_processor: DocumentProcessor,
             biometric_processor: BiometricProcessor) -> None: ...
```

```python
if session.status is VerificationStatus.PROCESSING:
    await self.document_processor.process(...)
    await self.biometric_processor.process(...)   # NEW -- runs after
                                                     # document processing,
                                                     # same PROCESSING step
    decision = await self.decision_orchestrator.evaluate_and_persist(...)
```

**Ordering justification:** `biometric_processor.process()` must run
*after* `document_processor.process()` because route (A)'s reference
side depends on `DOCUMENT_FIELD_EXTRACTION`/`DOCUMENT_CLASSIFICATION`
already being effective (BP-001.5 §4's lineage graph). Both remain
unconditional no-ops when their respective capture types are absent —
`document_processor` already works this way; `biometric_processor` is
built to match (no `SELFIE`/`DOCUMENT` capture -> no rows, not an
error).

### Synchronous vs. asynchronous `submit()` — reasoned through, not assumed

Two real shapes exist:

```text
A. Synchronous (what's shown above)     B. Asynchronous / polling
   POST submit                             POST submit -> PROCESSING
        |                                       |
      wait                                  return immediately
        |                                       |
   complete result                         GET .../evidence (poll)
```

**FROZEN: A, for the demo, with the reasoning made explicit rather than
defaulted into.** This isn't introducing new architecture —
it's extending an already-shipped one. `document_processor.process()`
already runs synchronously inside this exact `submit()` branch today
(DP-001 Decision 4, live in production code, not a demo-only pattern).
More importantly, `submit()`'s own docstring (`core/verification/workflow.py:19-26`)
states `PROCESSING` is already designed as **a recovery state** — "a
session found sitting in `PROCESSING` is one an earlier `submit()` call
left behind mid-flight (crash, timeout) — recovered here by re-running
`evaluate_and_persist()`." That means the architecture already
anticipates a slow or interrupted processing step and already has a
resumption path for it (a client can safely retry `submit()`); adding
biometric processing to the same synchronous step extends a pattern
already built for exactly this situation, rather than stretching a
naive "always instant" assumption further than it was designed for.

**What this freeze does NOT claim, stated explicitly so it can't be
misread later:** this freezes synchronous processing only as a demo
execution model; it does not establish synchronous processing as
PaxLI's production scalability model. A KYC API's real latency budget
under concurrent load is a separate, later question, and (B) (or a
queue-backed variant) may well be the eventual production answer — this
plan scopes the decision to the demo only.

---

## Slice J — Demo API

- `/liveness` extended per Slice F's frozen resolution: bounded
  multi-file upload (`frames: list[UploadFile]`, demo default 5).
- No other new endpoints needed for capture — `/selfie`/`/document`
  already exist and are reused as-is.
- `submit()`'s existing response (`SessionEnvelope`) needs no schema
  change; the new evidence types simply appear in the session's
  evidence list via the already-existing `GET /{session_id}/evidence`.

---

## Slice K — Structured observability

No new logging infrastructure — `infrastructure/observability/logging.py`
(structlog, JSON, sanitized via `core/security/classification.sanitize_metadata`)
is reused unchanged. `BiometricProcessor`/document processor stages each
emit one `logger.info("stage_name", session_id=..., status=..., ...)`
event per stage — the sanitizer already guarantees no `HIGHLY_SENSITIVE`
payload content (embeddings, raw images) leaks into a log line, since
these calls log status/metadata, never `result` payloads directly (same
discipline every existing audit-event call site already follows).

---

## Slice L — Frontend

**Confirmed: no frontend exists anywhere in this repository.** From
scratch. Minimal scope for the demo: document capture, selfie capture,
liveness multi-frame capture (per Slice F), a submit trigger, and the
stage-by-stage visualization from your original request (`DOCUMENT`/
`BIOMETRIC`/`DECISION` sections with per-stage status).

**FROZEN: React + Vite + TypeScript.** Not Next.js (no SSR/routing need
for a single-flow demo), not React Native/Flutter (this is a
browser-based demo — direct browser camera API access is the whole
point). Kept deliberately small and explicitly disposable: no
authentication UI, merchant dashboard, billing, or tenant
administration — only document capture, selfie capture, the Temporal
Liveness Demo capture sequence, submit, processing state, evidence/
stage visualization, and the decision result. If PaxLI later needs a
real merchant-facing application, this demo UI is not meant to grow
into it — a deliberate boundary, not an oversight.

---

## Slice M — End-to-end integration

Full path: document capture → document processing (existing) → face
extraction from document (Slice G) → reference embedding (B/C/D) →
selfie capture → probe embedding (B/C/D) → liveness (F, if enabled) →
`FaceMatch` (E) → Decision Engine (existing, zero change per BP-001
§3/§4/Decision 11).

---

## Slice N — Hostile validation

Reuses this project's existing HV discipline (HV-009 through HV-013's
precedent), scoped to what Slices A-M actually add. Draft matrix, to be
expanded at HV time, not frozen here:

```text
Document: blurry, rotated, poor lighting, unsupported type
Face:     no face, multiple faces, poor quality, extreme pose
Liveness: single-frame-only submission (protocol violation), replay
          (same frame N times)
Matching: model-version mismatch (Slice E's compatibility path),
          missing reference, missing probe, FaceMatch recomputation
          on either side's supersession
System:   concurrent submit() calls, tenant isolation across the new
          evidence types, InsightFace/ONNX Runtime failure injection
          (CapabilityUnavailableError path)
```

---

## Consolidated decision summary

**Status: all ten items resolved as of reconciliation pass 2.** Eight
are FROZEN; two (PaddleOCR's exact model, InsightFace's internal
session topology) are deliberately classified as implementation-time
freedoms rather than open architecture — a different, weaker kind of
"open" than an unresolved decision, and recorded that way on purpose so
neither gets mistaken for a gap in the plan.

| # | Decision | Final state |
|---|---|---|
| 1 | `ReferenceSourceResolver`/`DocumentFaceExtractor` boundary, separated from `BiometricProcessor` | **FROZEN** — Slice G |
| 2 | Candidate-face selection when a document has 0/1/>1 faces | **FROZEN** — explicit rule, no largest-face heuristic — Slice G |
| 3 | Does low `FaceQuality` gate `FaceEmbedder`? | **FROZEN — no gating.** Always attempt embedding when a candidate exists; quality persists as independent evidence — Slice C |
| 4 | Liveness capture protocol | **FROZEN — (i), bounded multi-file upload**, demo default 5 frames — Slice F |
| 5 | Liveness demo terminology/guarantee boundary | **FROZEN** — "Liveness Heuristic Demo"/"Temporal Liveness Demo" required on every surface — Slice F |
| 6 | `FaceMatch` incompatibility status/reason-code mapping | **FROZEN — `INCONCLUSIVE` + `core/face/reason_codes.py:REPRESENTATION_INCOMPATIBLE`**, reasoned from the `DOCUMENT_FIELD_EXTRACTION` precedent; `FAIL` stays reserved for a genuine future negative-comparison outcome, never used by this plan — Slice E |
| 7 | Synchronous vs. asynchronous `submit()` processing | **FROZEN — synchronous, for the demo only.** Explicitly does NOT establish synchronous processing as PaxLI's production scalability model — Slice I |
| 8 | Exact PaddleOCR model/package/language pack | **Implementation-time technology selection**, not an open architectural decision — install, inspect, select, benchmark, record, implement (Slice A's own frozen process) |
| 9 | Frontend framework/tooling | **FROZEN — React + Vite + TypeScript**, deliberately disposable, no product-surface scope creep — Slice L |
| 10 | InsightFace internal session/module topology | **Explicitly NOT to be frozen** — implementation detail subject to measurement, per TD-001's own counter-intuitive restricted-module result — Slice B |

Everything in Slices A-N is now either a direct, traceable application
of already-frozen BP-001/BP-001.5/TD-001 decisions, a decision frozen
in this pass, or an explicitly-named implementation-time freedom. No
item remains genuinely undecided.
