# DP-002 — Document Processing Phase 1 Implementation Plan

**Status:** PLAN — no production code changed yet. This document locks the Phase 1 implementation boundary from DP-001's seven frozen decisions; it makes no new architectural decisions. Where a genuinely new (but narrow, implementation-level) choice is unavoidable, it is called out explicitly as an assumption, not silently folded in.
**Depends on:** `docs/decisions/DP-001-document-processing-discovery.md` (all 7 decisions FROZEN).
**Scope:** deterministic `QualityAssessor` + `DocumentClassifier` only, producing real `DOCUMENT_QUALITY`/`DOCUMENT_CLASSIFICATION` `EvidenceResult` rows through the real `/submit` pipeline into the existing, unmodified Decision Engine.

---

## 1. Capability contracts

New module: `core/document/capabilities.py`. Replaces `core/document/provider.py`'s `DocumentProvider`/`DocumentEvidence`, which is deleted (DP-001 Decision 3).

Domain types first — plain dataclasses, matching the existing `FaceEvidence`/`LivenessEvidence` convention, never `EvidenceResult`:

```python
# core/document/types.py

class DocumentType(StrEnum):
    """DP-001 Decision 5's V1 catalog. Closed vocabulary -- never a free
    string. Absence of a match is represented by DocumentClassification.
    document_type=None, not by a member of this enum."""
    STANDARD_NIN_SLIP = "STANDARD_NIN_SLIP"
    IMPROVED_NIN_SLIP = "IMPROVED_NIN_SLIP"
    ICAO_PASSPORT_DATA_PAGE = "ICAO_PASSPORT_DATA_PAGE"


@dataclass(frozen=True)
class QualityAssessment:
    quality_score: float


@dataclass(frozen=True)
class DocumentClassification:
    """document_type=None means: no catalog member matched. DocumentProcessor
    -- not this type, not the capability -- decides that this maps to
    DOCUMENT_CLASSIFICATION status=FAIL, reason=DOCUMENT_UNSUPPORTED
    (DP-001 Decision 5)."""
    document_type: DocumentType | None
    confidence: float | None = None


@dataclass(frozen=True)
class OCRExtraction:
    """Raw, per-source, non-canonical -- DP-001 Decision 7 explicitly keeps
    this shape unchanged; only DOCUMENT_FIELD_EXTRACTION gets the hybrid
    canonical schema."""
    fields: dict[str, str]


@dataclass(frozen=True)
class MRZExtraction:
    raw: str
    fields: dict[str, str]


@dataclass(frozen=True)
class BarcodeExtraction:
    raw: str
    fields: dict[str, str] = field(default_factory=dict)
```

Capability ports — one per DP-001 Decision 3's six independently-failable stages:

```python
# core/document/capabilities.py

class QualityAssessor(ABC):
    @abstractmethod
    async def assess(self, image: bytes) -> QualityAssessment: ...

class DocumentClassifier(ABC):
    @abstractmethod
    async def classify(self, image: bytes) -> DocumentClassification: ...

class OCREngine(ABC):
    @abstractmethod
    async def extract(self, image: bytes) -> OCRExtraction: ...

class MRZParser(ABC):
    @abstractmethod
    async def parse(self, image: bytes) -> MRZExtraction | None: ...
    # None = no MRZ zone present -- a legitimate outcome (-> MRZ=NOT_SUBMITTED),
    # never an error.

class BarcodeDecoder(ABC):
    @abstractmethod
    async def decode(self, image: bytes) -> BarcodeExtraction | None: ...
    # None = no barcode/QR present -> BARCODE_QR=NOT_SUBMITTED.
```

**`AuthenticityChecker` is NOT defined in Phase 1.** DP-001 Decision 6 froze that `DOCUMENT_AUTHENTICITY` receives no implementation through Phase 4 of this vertical slice at all — there is nothing for an interface to serve yet, and defining an ABC with no planned caller and no planned implementation is speculative surface area this project's own discipline argues against. It gets designed if and when a dedicated future discovery (per DEF-9.15.3) identifies a real signal.

`OCREngine`/`MRZParser`/`BarcodeDecoder` interfaces above ARE defined now (per Decision 3's explicit allowance) so `DocumentProcessor`'s Phase-2 orchestration shape doesn't need rework later — but they get **zero implementations, deterministic or real, in Phase 1**.

---

## 2. Phase 1 implementations

`core/document/deterministic.py`:

```python
class DeterministicQualityAssessor(QualityAssessor):
    """Fixed, content-independent scoring -- proves the orchestration/
    lineage/persistence path, not real blur/glare/crop detection.
    Explicitly NOT a stand-in for a real quality model's behavior."""
    async def assess(self, image: bytes) -> QualityAssessment: ...

class DeterministicDocumentClassifier(DocumentClassifier):
    """Matches against the DP-001 Decision 5 catalog using a fixed,
    inspectable rule (not ML) -- e.g. keyed off already-known test-fixture
    byte signatures. Returns document_type=None for anything else,
    exercising the DOCUMENT_UNSUPPORTED path deliberately, not just the
    happy path."""
    async def classify(self, image: bytes) -> DocumentClassification: ...
```

Both must have an explicit, easily-triggered path to their *unsatisfying* outcome (a low quality score; an unrecognized document) in addition to their happy path — Phase 1's job is to prove `DOCUMENT_QUALITY=FAIL`/`INCONCLUSIVE` and `DOCUMENT_CLASSIFICATION=FAIL`/`DOCUMENT_UNSUPPORTED` flow correctly through to policy evaluation, not just the `PASS` case.

---

## 3. Required schema changes (small, scoped)

- `core/evidence_result/schemas.py`: `DocumentClassificationResult.document_type` changes from `str` to `DocumentType` (DP-001 Decision 5: "controlled vocabulary, never an unrestricted free-form string"). This is the one schema change Phase 1 actually needs.
- `core/evidence_result/classification.py`: apply DP-001 Decision 1's reclassification (`OCR_EXTRACTION`, `MRZ`, `BARCODE_QR`, `DOCUMENT_FIELD_EXTRACTION` → `HIGHLY_SENSITIVE`) now, even though none of these four types are touched by Phase 1's actual capabilities. Doing it now costs nothing (zero real rows exist for any of them yet, confirmed in DP-001's discovery) and closes the conformance gap immediately rather than leaving it open until Phase 2 for no reason.
- `DocumentFieldExtractionResult`'s hybrid schema (DP-001 Decision 7) is **not** built in Phase 1 — it belongs to Phase 2, when `OCREngine`/`MRZParser`/`BarcodeDecoder` actually produce inputs for it.

---

## 4. `DocumentProcessor`

New module: `core/document/processor.py`.

```python
class DocumentProcessor:
    def __init__(
        self,
        evidence_repository: EvidenceRepository,
        evidence_result_service: EvidenceResultService,
        quality_assessor: QualityAssessor,
        document_classifier: DocumentClassifier,
    ) -> None: ...

    async def process(
        self, *, session_id: UUID, tenant_id: str,
        request_id: str | None, correlation_id: str | None,
    ) -> None:
        """Called unconditionally from VerificationWorkflowService.submit()'s
        PROCESSING branch (DP-001 Decision 4). No-ops if no DOCUMENT-type
        capture exists for this session -- REQUIRED_EVIDENCE_MISSING, if
        applicable, is the Decision Engine's job via policy evaluation,
        not this method's."""
```

**Capture selection — AMENDED per reconciliation.** DP-001's discovery confirmed the capture side allows multiple `DOCUMENT`-type `Evidence` rows per session with no grouping/linking mechanism (no front/back, no multi-page concept exists). "Most recent wins" was rejected during reconciliation: it invents selection semantics nothing has frozen, for operational convenience alone. Instead:

> Phase 1 requires exactly one eligible `DOCUMENT` capture for authoritative document processing. Zero eligible captures is a silent no-op (the Decision Engine's existing `REQUIRED_EVIDENCE_MISSING` policy mechanism handles absence correctly; `DocumentProcessor` need not act). More than one eligible capture is an explicit ambiguity condition, not a selection problem — see below. No implicit "latest wins" or similar rule is introduced. Multi-document selection/grouping (front/back, retries-as-replacement, explicit roles) is deferred to a future architectural decision, not decided here.

**Ambiguity handling.** Per Part III's own constitutional principle — *"PaxLI must never infer certainty from ambiguity"* — more than one eligible `DOCUMENT` capture is not an infrastructure failure (`UNAVAILABLE` would be the wrong status; nothing about the capabilities is unavailable) and not a judged negative result (`FAIL` would imply a check ran and failed). It is checked as a **precondition, before any capability is invoked** — the same shape as `SessionHasNoPolicyPinError`'s precondition check ahead of any evaluation work:

```python
captures = [e for e in await evidence_repository.list_for_session(session_id, tenant_id)
            if e.evidence_type is EvidenceType.DOCUMENT]
if len(captures) == 0:
    return  # no-op; REQUIRED_EVIDENCE_MISSING is the Decision Engine's concern
if len(captures) > 1:
    for stage in (DOCUMENT_QUALITY, DOCUMENT_CLASSIFICATION):
        await evidence_result_service.create(
            status=EvidenceResultStatus.INCONCLUSIVE,
            reason_codes=("AMBIGUOUS_DOCUMENT_CAPTURE",),
            ...  # no source_reference to a single capture -- there isn't one
        )
    return
capture = captures[0]
# proceed with the single eligible capture
```

**Per-stage convergence (DP-001 Decision 4):**

```python
for each stage in (quality, classification):
    existing = await evidence_result_service.list_effective_for_session_by_type(...)
    if existing and is_reusable(existing.status):   # PASS/FAIL/DOCUMENT_UNSUPPORTED = reusable, terminal
        continue                                     # skip -- do not recompute
    try:
        result = await capability(...)
    except CapabilityUnavailableError as exc:
        await evidence_result_service.create(status=UNAVAILABLE, reason_codes=(exc.reason_code,), ...)
        continue
    # any OTHER exception propagates uncaught -- see failure taxonomy below
    await evidence_result_service.create(status=..., result=..., source_reference=capture.id, ...)
```

`is_reusable()` is Phase 1's first concrete instance of DP-001's carried-forward open item (the full reusable-vs-retryable matrix per `EvidenceResultStatus`). For Phase 1's two deterministic capabilities specifically: `PASS`/`FAIL`/`INCONCLUSIVE` (the ambiguity case) are terminal (reusable); `UNAVAILABLE` is retryable (a prior known-failure doesn't permanently block a retry). This is a narrow, Phase-1-scoped instance of that matrix, not the full general answer — the full matrix stays open for Phase 2+ where genuinely retryable-with-a-budget states become relevant.

**Failure taxonomy — AMENDED per reconciliation.** The original wording ("a capability call raising is caught and converted to `UNAVAILABLE`") was too broad: catching bare `Exception` would silently normalize a genuine programming defect (an `AttributeError`, a `KeyError`, an `AssertionError` from a bug in `DocumentProcessor`'s own calling code or a capability's implementation) into an indistinguishable, ordinary-looking `DOCUMENT_QUALITY = UNAVAILABLE` row — exactly the kind of "safe failure that hides a defect" HV-006 already established this project must not do. The corrected rule:

```python
class CapabilityUnavailableError(Exception):
    """Raised by a capability implementation for a known, expected,
    self-diagnosed failure (model unavailable, timeout, recognized
    malformed input) that DocumentProcessor translates into a stage-level
    UNAVAILABLE EvidenceResult. Capabilities MUST NOT use this for
    anything they cannot positively identify as an expected failure mode.
    Any OTHER exception -- a bug, an invariant violation, a configuration
    error -- is NOT this project's business to reinterpret as ordinary
    capability unavailability. It propagates uncaught, reaches the
    existing WF-006 catch-all, and surfaces as a logged, observable 500 --
    never silently normalized."""
    def __init__(self, reason_code: str) -> None: ...
```

`DocumentProcessor` catches only `CapabilityUnavailableError`, never bare `Exception`. Known capability/inference failures are translated into typed stage outcomes; unexpected programming, invariant, or configuration failures remain distinguishable and observable, not silently absorbed. Phase 1's deterministic stub implementations likely never raise this at all — a pure function over already-validated bytes has no genuine "known failure" case — but the type and the catch boundary exist now because Phase 3's real adapter will need to raise it for genuine model-unavailable/timeout conditions.

A failure to *persist* an evidence result (a genuine DB-level failure, not a capability failure) is a different class of problem again and is allowed to propagate — matching the exact HV-009 evidence-read-failure precedent (`DecisionOrchestrator._handle_context_read_failure`), where an infrastructure failure that prevents recording anything at all becomes a safe generic 500 via the existing catch-all, not a fabricated evidence row.

**Concurrency:** `QualityAssessor` and `DocumentClassifier` are both first-order (read the capture directly, no dependency on each other) and MAY run concurrently — each in its own `async with session_factory()` block per DP-001 Decision 4's explicit implementation note. Given only two independent stages exist in Phase 1, this is a small, easily-verified case, not the full N-stage concurrent-DAG scheduling Phase 2 will eventually need.

**Reliability wrapper scope, explicitly narrowed for Phase 1:** no `CircuitBreaker`/`RetryPolicy`/timeout wrapper (the `infrastructure/reliability/minio_policies.py` pattern) is built around these calls in Phase 1. A deterministic, pure, in-process function has nothing genuine to circuit-break or retry against — building that machinery now would be protecting against a failure mode that doesn't exist yet. The bare try/except above is Phase 1's complete reliability story; the full guarded-wrapper pattern is Phase 3's job, once a real adapter that can genuinely time out or degrade exists.

---

## 5. Workflow integration

`core/verification/workflow.py`'s `VerificationWorkflowService` gains a new required constructor dependency:

```python
class VerificationWorkflowService:
    def __init__(
        self,
        session_service: VerificationSessionService,
        decision_orchestrator: DecisionOrchestrator,
        audit_service: AuditService,
        document_processor: DocumentProcessor,   # NEW
    ) -> None: ...
```

The `PROCESSING` branch (`workflow.py:131-156`) gains one call, unconditional, before the existing `evaluate_and_persist()` call:

```python
if session.status is VerificationStatus.PROCESSING:
    await self.document_processor.process(
        session_id=session.id, tenant_id=session.tenant_id,
        request_id=request_id, correlation_id=correlation_id,
    )
    evaluation_reason = ...   # unchanged
    decision = await self.decision_orchestrator.evaluate_and_persist(...)  # unchanged
    session = await self._advance(session, VerificationStatus.COMPLETED, ...)  # unchanged
    continue
```

`apps/api/paxli_api/dependencies.py`'s `get_workflow_service()` gains the corresponding wiring: construct `DocumentProcessor` with `SqlAlchemyEvidenceRepository`, the existing `EvidenceResultService` (already built in that function), and the two deterministic capability implementations from `core/document/deterministic.py`.

Capture endpoints (`/document`, `/selfie`, `/liveness`) are untouched — confirming DP-001 Decision 4's boundary held through to the concrete wiring, not just the prose.

---

## 6. Testing strategy

Following this project's established layering:

- **`tests/unit/`**: `DeterministicQualityAssessor`/`DeterministicDocumentClassifier` behavior (happy path + unsatisfying path each); `DocumentProcessor` convergence logic against fakes (reusable result skipped, non-reusable result retried, `CapabilityUnavailableError` converted to `UNAVAILABLE`); the ambiguity precondition (zero captures no-ops; exactly one proceeds; two-or-more produces `INCONCLUSIVE`/`AMBIGUOUS_DOCUMENT_CAPTURE` for every stage, with zero capability calls made — the precondition check must short-circuit before invoking anything).
- **A dedicated test proving the exception-taxonomy boundary itself**: a fake capability that raises a bare `AttributeError` (simulating a real programming defect, not a `CapabilityUnavailableError`) must propagate out of `DocumentProcessor.process()` uncaught — asserted directly (`pytest.raises`), not inferred. This is the test that would have caught the original "catch bare `Exception`" draft before it shipped.
- **`tests/integration/`** (real Postgres): full `DocumentProcessor.process()` round-trip producing real `DOCUMENT_QUALITY`/`DOCUMENT_CLASSIFICATION` `EvidenceResult` rows with correct `source_reference` lineage; a retried `process()` call proven (via call-count assertion on the capability, not just outcome) not to re-invoke a capability whose stage already has an effective, reusable result; a full `/submit` HTTP-level test producing a real decision driven by document evidence, mirroring `test_decision_orchestration.py`'s existing full-pipeline pattern; a real two-`DOCUMENT`-capture session proving the ambiguity path end to end through a real `/submit` call.
- **`tests/contracts/`**: the `DOCUMENT_UNSUPPORTED` path — an unrecognized document classifies to `FAIL`/`DOCUMENT_UNSUPPORTED` and the *Decision Engine*, not `DocumentProcessor`, determines the session outcome (two different policies producing two different outcomes from the identical evidence, proving the separation is real, not just documented).
- **Concurrency**: a barrier-synchronized test (matching this project's established HV-007-style methodology) proving `QualityAssessor` and `DocumentClassifier` genuinely run concurrently without interfering, each committing independently.
- **Hostile validation immediately after Phase 1 lands** (a short HV-010, scoped narrowly to what Phase 1 actually introduces): can a malformed/adversarial capture crash `DocumentProcessor` rather than degrading safely to `UNAVAILABLE`? Do the existing tenant/session-safety guarantees (HV-009 Findings A/B, already proven for `EvidenceResultService` generically) hold for real `DOCUMENT_QUALITY`/`DOCUMENT_CLASSIFICATION` rows specifically, or does `DocumentProcessor` introduce some new bypass? This is expected to be confirmatory, not defect-finding, given it rides entirely on already-hardened `EvidenceResultService` machinery — but it gets checked, not assumed.

---

## 7. Explicit non-goals for Phase 1

- No `OCREngine`/`MRZParser`/`BarcodeDecoder` implementation (interfaces only, per §1).
- No `AuthenticityChecker` at all — not even the interface (DP-001 Decision 6).
- No `DOCUMENT_FIELD_EXTRACTION`, `MRZ`, `BARCODE_QR`, or `IDENTITY_CONSISTENCY` `EvidenceResult` production. Phase 1 MUST NOT modify, finalize, or informally extend `DOCUMENT_FIELD_EXTRACTION`'s schema beyond what DP-001 Decision 7 already ratified — no convenience structure introduced for `DOCUMENT_QUALITY`/`DOCUMENT_CLASSIFICATION`'s own needs may quietly become a de facto precedent for the document field schema Phase 2 has to build.
- No cross-source reconciliation algorithm (nothing to reconcile yet).
- No real ML/OCR/model-serving library or dependency of any kind.
- No `CircuitBreaker`/`RetryPolicy`/timeout wrapper around capability calls (§4's explicit scope narrowing).
- No async worker, queue, or durable job infrastructure (unchanged from DP-001; still TARGET v1.1).
- No external identity-provider integration.
- No multi-page/front-back document grouping mechanism, and no implicit selection rule (e.g. "most recent wins") standing in for one — Phase 1 requires exactly one eligible `DOCUMENT` capture and treats more than one as an explicit `INCONCLUSIVE`/`AMBIGUOUS_DOCUMENT_CAPTURE` condition instead (§4, amended during reconciliation).
- No blanket exception handling in `DocumentProcessor` — only `CapabilityUnavailableError` is caught; unexpected defects propagate and surface observably (§4, amended during reconciliation).
- No changes to `DecisionOrchestrator`, `core/policy/`, or any WF/DE/HV-frozen contract.

---

## 8. Closure criteria

Phase 1 is done when: `DocumentProcessor` is wired into `submit()`, produces real, correctly-lineaged `DOCUMENT_QUALITY`/`DOCUMENT_CLASSIFICATION` `EvidenceResult` rows for both the happy and unsatisfying path of each capability, a policy can require and condition on either type today (unmodified Decision Engine), retried `/submit` calls converge without re-invoking already-satisfied stages, the full test suite (existing + new) passes twice consecutively, mypy/ruff are clean, and the scoped HV-010 pass against this new surface comes back clean or with findings triaged the same way every HV-00X finding has been this session — fixed, disclosed, or explicitly deferred, never silently ignored.
