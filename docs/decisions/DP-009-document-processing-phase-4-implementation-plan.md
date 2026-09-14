# DP-009 — Document Processing Phase 4 Implementation Plan

**Status: FROZEN.** Locks DP-008's frozen decisions (and DP-001 Addendum
A) into code shape, mirroring DP-002/DP-004/DP-006's structure. Three
implementation-level questions were surfaced while grounding this plan
against the actual current codebase (not assumed from DP-008 alone) —
§7.1, §7.2, and §7.3 are all resolved after two reconciliation passes.
This document does not re-litigate anything DP-008 or DP-001 Addendum A
already froze; where it appears to, it is translating a frozen decision
into code, not deciding it fresh. **Implementation is now authorized
against this plan** — starting with §1's schema/domain boundary, not the
processor.

**Depends on:** `docs/decisions/DP-008-document-processing-phase-4-discovery.md`
(all decisions FROZEN/SELECTED), `docs/decisions/DP-001-document-processing-discovery.md`
Decision 7 as amended by Addendum A, `docs/decisions/DP-005-document-processing-phase-3-ocr-discovery.md`
/ `DP-006-...-implementation-plan.md` (the outcome-wrapper pattern this
plan follows where it applies, and deliberately does not force where it
doesn't — see §3).

**Scope:** implement `DOCUMENT_FIELD_EXTRACTION` as a sixth
`DocumentProcessor` stage, consuming the already-persisted effective
`OCR_EXTRACTION`/`MRZ`/`BARCODE_QR` results for the same capture,
producing a canonicalized, conflict-aware result via a dedicated domain
reconciler (DP-008 §5). No changes to `_run_quality`/`_run_classification`/
`_run_mrz`/`_run_barcode`/`_run_ocr`, no changes to any WF/DE/HV-frozen
contract, no real normalization/comparison library selection (the
concrete algorithm is this plan's own job — see §4 — but no external
dependency is introduced).

---

## 1. Schema and domain-type changes

`core/evidence_result/schemas.py` — replaces the current placeholder
(`fields: dict[str, str]`) with DP-001 Decision 7's frozen shape, as
amended by Addendum A:

```python
class DocumentFieldExtractionResult(BaseModel):
    full_name: str | None
    surname: str | None
    given_names: str | None
    date_of_birth: str | None
    sex: str | None
    document_number: str | None
    nationality: str | None
    expiry_date: str | None
    extensions: dict[str, str]
    conflicted_fields: tuple[str, ...] = ()
```

`core/document/types.py` — a new pure domain result the reconciler
returns (never `EvidenceResultStatus`, matching every other type in this
module — DP-001 Decision 3's domain/persistence boundary):

```python
_CANONICAL_FIELD_NAMES = (
    "full_name", "surname", "given_names", "date_of_birth",
    "sex", "document_number", "nationality", "expiry_date",
)

@dataclass(frozen=True)
class FieldReconciliationResult:
    """Returned by DocumentFieldReconciler.reconcile() -- always, never
    None (mirrors OCR's non-optional contract: field reconciliation is
    applicable whenever this stage runs at all; the ambiguous-capture
    precondition, not this type, is what decides whether the stage runs
    -- DP-008 §5's interface-completeness resolution). Field names in
    conflicted_fields are drawn only from _CANONICAL_FIELD_NAMES (DP-008
    §3.5's frozen invariant, restated here as a constructor-time
    assertion, not left as a documentation-only promise)."""

    full_name: str | None
    surname: str | None
    given_names: str | None
    date_of_birth: str | None
    sex: str | None
    document_number: str | None
    nationality: str | None
    expiry_date: str | None
    extensions: dict[str, str]
    conflicted_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        unknown = set(self.conflicted_fields) - set(_CANONICAL_FIELD_NAMES)
        if unknown:
            raise ValueError(f"conflicted_fields contains non-canonical names: {unknown}")
        for name in self.conflicted_fields:
            if getattr(self, name) is not None:
                raise ValueError(
                    f"conflicted_fields lists {name!r} but its value is not null "
                    "(DP-008 §3.5: a listed field MUST be null)"
                )
```

This dataclass is deliberately the *only* new domain type Phase 4 adds —
unlike MRZ/Barcode/OCR, there is no separate `*Extraction` (raw
observation) vs. `*ReadResult` (outcome wrapper) split, and no
`*ReadOutcome` enum. Reasoning in §3.

## 2. Reason code

`core/document/reason_codes.py` gains one member, following the module's
established bare-name convention:

```python
    # DP-008 §3.5/§6 (Phase 4): the one outcome this stage can report
    # that none of OCR/MRZ/Barcode's own reason codes cover -- a
    # cross-source canonical-field disagreement, never a single source's
    # own failure to read/parse (those already have their own codes on
    # their own EvidenceResult rows).
    FIELD_VALUE_CONFLICT = "FIELD_VALUE_CONFLICT"
```

## 3. The reconciler's domain contract — not a `capabilities.py` port

New module, `core/document/reconciliation.py`, per DP-008 §5's selected
architecture (dedicated domain reconciler, not an image-processing
capability, not `DocumentProcessor`-internal logic):

```python
"""DP-008 §5: DocumentFieldReconciler is deliberately NOT defined in
core/document/capabilities.py. It shares that module's domain-result
discipline (never EvidenceResultStatus, never a persistence identifier)
but not its contract shape -- every capabilities.py port is
`image: bytes -> domain result`; this is
`domain observations -> derived domain observation`. Forcing it into
the bytes-in port shape would misrepresent what that abstraction is for
in this codebase (an adapter seam for a future real implementation --
nothing about reconciliation will ever have one, DP-008 §5 point 3).

Synchronous, not async, unlike every capabilities.py port: this is pure
computation over already-fetched domain values, with no I/O of its own
-- honest about what it actually does, and consistent with there being
no CapabilityUnavailableError-shaped failure mode for it either (see the
class docstring below).
"""

from core.document.types import BarcodeExtraction, FieldReconciliationResult, MRZExtraction, OCRExtraction


class DocumentFieldReconciler(ABC):
    """No CapabilityUnavailableError analog: unlike OCR/MRZ/Barcode,
    there is no external model/dependency this can report as
    unavailable -- it is pure logic over inputs DocumentProcessor has
    already fetched. Any exception out of reconcile() is a programming
    defect, propagating uncaught exactly like every other unexpected
    exception in this pipeline (DP-002 reconciliation amendment B),
    never silently converted to an UNAVAILABLE result."""

    @abstractmethod
    def reconcile(
        self,
        *,
        ocr: OCRExtraction | None,
        mrz: MRZExtraction | None,
        barcode: BarcodeExtraction | None,
    ) -> FieldReconciliationResult:
        """Each parameter is None exactly when that source was ABSENT
        for this capture (DP-008 §3.7: NOT_SUBMITTED/UNAVAILABLE status,
        or for OCR, UNREADABLE) -- WHY a source is None is never encoded
        here; it stays reconstructible from that source's own persisted
        EvidenceResult via parent_evidence_result_ids (DP-008 §3.4/§5's
        interface-completeness resolution). Always returns a populated
        result, never None -- DOCUMENT_FIELD_EXTRACTION has no
        capability-level absence state of its own; if this method is
        called at all, all three inputs already went through
        DocumentProcessor's ambiguous-capture precondition."""
        raise NotImplementedError
```

**Why `ocr`/`mrz`/`barcode` are typed as the raw `*Extraction` dataclasses,
not `*ReadResult`/`*ReadOutcome`:** the reconciler does not consume
source outcome vocabularies; it consumes only the source observations
(`raw`, `fields`, `symbology`) — the reconciler assigns no trust or
authority to any source, so it has no use for *why* a source produced
the data it did, only for the data itself. This is a statement about
what the reconciler's own input contract needs, not a claim that a
source's outcome is insignificant: `MRZReadOutcome.CHECK_DIGIT_MISMATCH`
is deliberately not passed into `reconcile()`, but it remains fully
meaningful downstream — source outcome/status semantics stay on the
persisted parent `EvidenceResult` rows for the Decision Engine's own
interpretation, exactly as EVD-3.25.1 requires them to (§7.1).
`DocumentProcessor` is responsible for collapsing each sibling's
persisted `EvidenceResultStatus` + `result` into either an `*Extraction`
value or `None` before calling `reconcile()` — the same responsibility it
already has translating capability outputs into persisted rows, just
running in the other direction for this one stage. **§7.1 (resolved): a
populated extraction is passed through regardless of whether the
source's own `status` was `PASS` or `FAIL`** — see §5.3 and §7.1 for the
full reasoning.

## 4. Deterministic implementation

`core/document/deterministic.py` gains `DeterministicFieldReconciler`.
Per DP-008 §3.11 (reconciler owns source→canonical mapping) and §3.7
(normalization-before-comparison policy), this needs, at minimum:

1. **A source→canonical field-name mapping per source.** Each of
   OCR/MRZ/Barcode's `fields` dicts uses its own vocabulary (§2.4 of
   DP-008's research). For the deterministic implementation (test-fixture
   driven, mirroring every other deterministic capability's marker-based
   design), the mapping can be a fixed dict per source rather than a
   document-type-specific registry — the document-type-specific
   generalization DP-008 §3.11 flagged as a future concern is not needed
   until a real adapter exists.
2. **A normalization function per canonical field type**, applied
   identically to every source's raw value before comparison (DP-008
   §3.7's frozen policy: compare canonical normalized values, never raw
   strings). "Per field type" means exactly one normalization function
   for, say, `full_name` — applied the same way regardless of which
   source (OCR/MRZ/Barcode) supplied the value. There is no per-source
   variant: `OCR -> normalize_A`, `MRZ -> normalize_B` would make the
   comparison itself untrustworthy (two sources could "agree" or
   "disagree" purely as an artifact of which normalizer ran on which
   side, not because of the underlying data), defeating the entire
   purpose of normalizing before comparison in the first place. For the
   deterministic implementation, keep this genuinely minimal —
   whitespace/case normalization for name fields, no real date-parsing
   library — since the deterministic baseline's job (matching Phase 1-3's
   own precedent) is to prove the orchestration/persistence/conflict-
   representation contract, not to be a production-grade reconciliation
   algorithm. This symmetry invariant is exactly what HV-013 (§9) should
   attack directly, not just the deterministic baseline's happy path.
3. **Agreement/disagreement/insufficient logic per §3.7's frozen
   states**, producing `FieldReconciliationResult`.

This mirrors Phase 1-3's own discipline: a deterministic stand-in proves
the contract; a real reconciliation algorithm (real date/name
normalization, a real per-document-type mapping registry) is future work
behind the same interface, exactly as OCR/MRZ/Barcode's real adapters
remain future work behind theirs.

**§7.3 (resolved): `extensions` is always `{}` in the deterministic
baseline.** Phase 4 reconciles the eight canonical fields only —
`DeterministicFieldReconciler.reconcile()` never populates `extensions`
from any source's unmapped `fields` keys. Reasoning: naively merging
`ocr.fields`/`mrz.fields`/`barcode.fields` for any key outside the
canonical mapping would silently collide three independently-chosen
vocabularies against each other (the exact "invented reconciliation
surface" DP-008 spent its entire discovery pass ruling out for the
canonical fields — extending that same risk to an ad hoc merge of
*everything else* would undo the discipline for no benefit). DP-001
Decision 7 already makes `extensions` non-policy-addressable in V1, so
there is no consumer today that needs it populated. If a future phase
identifies specific, named, collision-free document-specific fields
worth preserving (e.g. a passport's issuing-state code), that is its own
explicit decision, made when a real consumer exists — not invented ahead
of need here.

## 5. `DocumentProcessor` extension

### 5.1 Constructor

`SqlAlchemyDocumentProcessor.__init__` gains a 10th positional parameter,
`field_reconciler: DocumentFieldReconciler`, stored as
`self._field_reconciler` — mirroring every prior phase's rollout
mechanics exactly (and the exact class of call-site breakage DP-002/
DP-004/DP-006 each went through and fixed: every direct-construction test
site needs updating).

### 5.2 `process()`

One more call appended after `_run_ocr`, unconditionally, matching every
prior stage's own precedent (DP-003 Decision 7 / DP-005 Decision 3's
"invoked unconditionally" pattern) — the ambiguous-capture precondition
is what actually gates invocation, not document-type branching:

```python
await self._run_field_extraction(
    session_id=session_id, tenant_id=tenant_id,
    capture_id=capture_id, object_key=object_key, ambiguous=ambiguous,
    request_id=request_id, correlation_id=correlation_id,
)
```

`object_key` is threaded through for signature consistency with every
other `_run_*` method, but `_run_field_extraction` never calls
`self._storage.get(object_key)` — its input is the three sibling
`EvidenceResult` rows, not the capture image. Per DP-001 Decision 2's
own already-frozen wiring rule ("a stage MAY populate both fields when
it directly examines the source capture and also consumes upstream
results" — implying a stage that does *not* directly examine the capture
populates only the field it needs), `_run_field_extraction` sets
`source_reference=None` and `parent_evidence_result_ids=(ocr.id, mrz.id,
barcode.id)` — never `capture_id`. This is DP-001's own rule applied, not
a new decision.

### 5.3 `_run_field_extraction`

```python
async def _run_field_extraction(
    self, *, session_id, tenant_id, capture_id, object_key, ambiguous,
    request_id, correlation_id,
) -> None:
    async with self._session_factory() as session:
        service = self._build_evidence_result_service(session)

        if ambiguous:
            existing = await service.get_effective_for_session_by_type(
                session_id=session_id, tenant_id=tenant_id,
                evidence_type=EvidenceResultType.DOCUMENT_FIELD_EXTRACTION,
            )
            if existing is not None and _is_reusable(existing.status):
                return
            await self._persist_stage(
                service, existing, session_id=session_id, tenant_id=tenant_id,
                evidence_type=EvidenceResultType.DOCUMENT_FIELD_EXTRACTION,
                status=EvidenceResultStatus.INCONCLUSIVE,
                reason_codes=(DocumentReasonCode.AMBIGUOUS_DOCUMENT_CAPTURE.value,),
                producer=_PRODUCER_FIELD_EXTRACTION,
                request_id=request_id, correlation_id=correlation_id,
            )
            await session.commit()
            return

        # The effective ROWS always exist by this point in process() --
        # OCR/MRZ/Barcode run strictly before this stage in the same
        # process() call (or a prior one), unconditionally, per DP-003
        # Decision 7/DP-005 Decision 3. A None ROW here would mean a
        # genuine ordering bug elsewhere in process(), not a legitimate
        # runtime state -- asserted below, not defensively handled. This
        # is distinct from a row's EXTRACTION being None: an existing row
        # with status=NOT_SUBMITTED/UNAVAILABLE/UNREADABLE is entirely
        # expected and translates to extraction=None per §7.1 -- the
        # assertion below only rules out the row itself being missing.
        ocr_row = await service.get_effective_for_session_by_type(
            session_id=session_id, tenant_id=tenant_id,
            evidence_type=EvidenceResultType.OCR_EXTRACTION,
        )
        mrz_row = await service.get_effective_for_session_by_type(
            session_id=session_id, tenant_id=tenant_id,
            evidence_type=EvidenceResultType.MRZ,
        )
        barcode_row = await service.get_effective_for_session_by_type(
            session_id=session_id, tenant_id=tenant_id,
            evidence_type=EvidenceResultType.BARCODE_QR,
        )
        assert ocr_row is not None and mrz_row is not None and barcode_row is not None

        current_parent_ids = (ocr_row.id, mrz_row.id, barcode_row.id)

        existing = await service.get_effective_for_session_by_type(
            session_id=session_id, tenant_id=tenant_id,
            evidence_type=EvidenceResultType.DOCUMENT_FIELD_EXTRACTION,
        )
        # DP-008 §4's frozen freshness principle, operationalized: reuse
        # requires BOTH the ordinary terminal-status check AND an
        # unchanged parent set -- a stale reconciliation built from a
        # superseded OCR/MRZ/Barcode row is never silently reused, even
        # if its own status looks terminal. Tuple equality, not set
        # equality: current_parent_ids is always constructed in this one
        # fixed (ocr, mrz, barcode) order, by this call site alone, and
        # the repository round-trips parent_evidence_result_ids order-
        # preservingly (a plain JSON list column, confirmed at
        # infrastructure/database/repositories/evidence_result.py:277-322
        # -- no reordering, no set storage) -- so a real lineage change
        # can never produce a spurious tuple match, and the stored
        # lineage stays exactly as auditable as it was written, not
        # merely set-equivalent to it.
        if (
            existing is not None
            and _is_reusable(existing.status)
            and existing.parent_evidence_result_ids == current_parent_ids
        ):
            return

        ocr_extraction = _to_ocr_extraction(ocr_row)
        mrz_extraction = _to_mrz_extraction(mrz_row)
        barcode_extraction = _to_barcode_extraction(barcode_row)

        result = self._field_reconciler.reconcile(
            ocr=ocr_extraction, mrz=mrz_extraction, barcode=barcode_extraction,
        )

        status = (
            EvidenceResultStatus.INCONCLUSIVE if result.conflicted_fields
            else EvidenceResultStatus.PASS
        )
        reason_codes = (
            (DocumentReasonCode.FIELD_VALUE_CONFLICT.value,) if result.conflicted_fields else ()
        )
        await self._persist_stage(
            service, existing, session_id=session_id, tenant_id=tenant_id,
            evidence_type=EvidenceResultType.DOCUMENT_FIELD_EXTRACTION,
            status=status, reason_codes=reason_codes,
            result={
                "full_name": result.full_name, "surname": result.surname,
                "given_names": result.given_names, "date_of_birth": result.date_of_birth,
                "sex": result.sex, "document_number": result.document_number,
                "nationality": result.nationality, "expiry_date": result.expiry_date,
                "extensions": result.extensions,
                "conflicted_fields": list(result.conflicted_fields),
            },
            producer=_PRODUCER_FIELD_EXTRACTION,
            parent_evidence_result_ids=current_parent_ids,
            request_id=request_id, correlation_id=correlation_id,
        )
        await session.commit()
```

No outcome-map dict (`_FIELD_EXTRACTION_OUTCOME_MAP`) the way
MRZ/Barcode/OCR each have one — deliberate deviation from that pattern,
stated explicitly rather than silently dropped: those maps exist to
protect a real multi-member outcome enum from a silently-unmapped new
member (the exhaustiveness tests in
`tests/unit/test_document_processor_outcome_maps.py`). This stage's
status is a pure function of one boolean (`conflicted_fields` empty or
not) with no enum in between — introducing one would be the "state
machinery for its own sake" DP-008 repeatedly rejected (§3.1, §3.12).

`_to_ocr_extraction`/`_to_mrz_extraction`/`_to_barcode_extraction` are
small module-level helpers translating a persisted `EvidenceResult` back
into the domain `*Extraction | None` shape §3 requires: `None` if
`status` is ABSENT per DP-008 §3.7 (`NOT_SUBMITTED`/`UNAVAILABLE`, or for
OCR, `UNREADABLE`) **or `result` is `None`** (the only way `result` is
`None` for a non-ABSENT status is OCR's `UNREADABLE`, already covered —
for MRZ/Barcode this branch is unreachable in practice but kept as a
defensive translation, not a new state); otherwise the extraction
dataclass reconstructed from `result["raw"]`/`result["fields"]` (plus
`result["symbology"]` for barcode) **regardless of whether `status` is
`PASS` or `FAIL`** — §7.1 (resolved): `_to_mrz_extraction` does NOT treat
`FAIL` as ABSENT. A `CHECK_DIGIT_MISMATCH` MRZ row's populated
`raw`/`fields` is passed through as a genuine observation; only
`UNREADABLE`/`NOT_SUBMITTED`/`UNAVAILABLE` collapse to `None`.

## 6. Required service-layer fix — found while grounding this plan, not assumed

**`EvidenceResultService.supersede()` does not accept
`parent_evidence_result_ids` today** (`core/evidence_result/service.py:299-316`)
— only `create()` does. Every prior stage's `_persist_stage` call never
needed this, because none of them populate `parent_evidence_result_ids`
at all. `DOCUMENT_FIELD_EXTRACTION` is the first stage that both (a) uses
`parent_evidence_result_ids` and (b) can go through the `supersede()`
branch of `_persist_stage` (on any recomputation triggered by §5.3's
freshness check) — a combination nothing before this phase exercised.

**Required fix:** add `parent_evidence_result_ids: tuple[UUID, ...] = ()`
to `EvidenceResultService.supersede()`'s signature, threaded into the new
`EvidenceResult` exactly as `create()` already does, validated through
the existing `_validate_provenance()` (already generic over both create
and supersede call sites — no change needed there). Without this fix, a
recomputed `DOCUMENT_FIELD_EXTRACTION` row would silently lose its
lineage on every retry after the first, breaking DP-008 §3.4's
reconstructibility invariant (the audit path that justifies not storing
`field_sources`) the very first time it's actually exercised. This is a
small, mechanical, narrowly-scoped fix to existing infrastructure, not a
new architectural decision — flagged here because it was found by reading
the actual current code, not something DP-008 discovery would have
surfaced (discovery didn't trace `supersede()`'s exact parameter list).

`_persist_stage` (`infrastructure/document/processor.py:254-307`) also
needs a new `parent_evidence_result_ids: tuple[UUID, ...] = ()` parameter,
threaded to both branches — mechanical, same shape as every other
parameter it already forwards.

## 7. Implementation-level questions surfaced and resolved during reconciliation

Three questions surfaced while writing §5/§6 against the actual codebase,
not settled by DP-008 (which operated one level of abstraction above
this). All three are now resolved.

### 7.1 RESOLVED: an MRZ row with `status=FAIL` (check-digit mismatch) is a usable reconciliation input, never ABSENT

DP-008 §3.7 defines ABSENT as `status ∈ {NOT_SUBMITTED, UNAVAILABLE}` (or
`UNREADABLE` for OCR) — `FAIL` is not in that list, and that omission is
read literally, not extended. A `CHECK_DIGIT_MISMATCH` MRZ row still
carries populated `raw`/`fields` (confirmed:
`infrastructure/document/processor.py:534-555`'s `_run_mrz` populates
`result_payload` for `CHECK_DIGIT_MISMATCH` exactly as it does for
`VALID`), and that populated observation is passed to the reconciler
exactly as a `PASS` row's would be.

**Governing principle:** "usable as reconciliation input" is not "trusted
as authoritative evidence." DP-008 already made the reconciler
conflict-*aware*, never conflict-*authoritative* — it compares
normalized source observations and exposes disagreement; it does not
decide which source is correct, and it assigns no extra trust to a
`PASS` source or extra suspicion to a `FAIL` one. The checksum failure
itself is not lost — it remains independently observable on MRZ's own
`EvidenceResult` row (`status=FAIL`, `reason_codes=("MRZ_CHECK_DIGIT_MISMATCH",)`),
satisfying EVD-3.25.1 regardless of how reconciliation treats the data.
Concretely: MRZ `FAIL` + OCR agreement → `DOCUMENT_FIELD_EXTRACTION` may
still `PASS`, while the Decision Engine separately sees MRZ's own `FAIL`
row; MRZ `FAIL` + OCR disagreement → `conflicted_fields` populated,
`DOCUMENT_FIELD_EXTRACTION=INCONCLUSIVE`, and the Decision Engine sees
both facts independently. This is the more faithful continuation of "the
reconciler reports facts; the Decision Engine interprets their
significance" — the same boundary §3.9's canonicalization-vs-authority
distinction already established. `_to_mrz_extraction` (§5.3) implements
this directly: it does not special-case `status=FAIL`.

### 7.2 RESOLVED: the `supersede()` fix is approved, with a required direct unit test

Approved as scoped in §6: `parent_evidence_result_ids: tuple[UUID, ...] = ()`
added to `EvidenceResultService.supersede()` and threaded through
`_persist_stage`, backward-compatible via the empty-tuple default. Beyond
§6's original scope: **this fix requires its own direct unit test of
`supersede()` preserving parent IDs** (`tests/unit/test_evidence_result_service.py`
or wherever `supersede()`'s existing unit coverage lives), not just
reliance on the processor-level freshness integration test in §9 — a
tight regression guard at the infrastructure boundary itself, since
`supersede()` is shared by every evidence type and any future caller of
it deserves the same guarantee, not only `DOCUMENT_FIELD_EXTRACTION`'s
own tests.

### 7.3 RESOLVED (new, added during reconciliation): `extensions` handling

See §4 — the deterministic reconciler always produces `extensions = {}`.
No cross-source merging of unmapped fields; only the eight canonical
fields participate in Phase 4 reconciliation. Full reasoning recorded in
§4 rather than duplicated here.

---

## 8. DI wiring

`apps/api/paxli_api/dependencies.py` — `DeterministicFieldReconciler`
imported and passed as the final positional arg to
`SqlAlchemyDocumentProcessor(...)` in `get_workflow_service()`, mirroring
DP-006 §6's exact rollout mechanics.

## 9. Testing strategy

Mirrors DP-006 §7/§8's structure and HV-012's coverage categories,
applied to the new stage:

- **Unit** (§7.2, `EvidenceResultService.supersede()`'s own test file):
  a direct test that `supersede()` persists a supplied
  `parent_evidence_result_ids` onto the new superseding row — infrastructure-
  boundary coverage, independent of and prior to the processor-level
  freshness test below.
- **Unit** (`tests/unit/test_document_deterministic.py`):
  `DeterministicFieldReconciler` — agreement, disagreement (per canonical
  field), insufficient (all-ABSENT), mixed outcomes across multiple
  fields in one call, a `FAIL`-status MRZ observation participating in
  both an agreement and a disagreement case (§7.1), confirmation
  `extensions` is always `{}` regardless of source `fields` content
  (§7.3), source→canonical mapping correctness per source.
- **Unit** (new or extended outcome-map-style test): confirm
  `FieldReconciliationResult.__post_init__`'s two invariants
  (`conflicted_fields` names are canonical-only;
  listed-field-implies-null) are actually enforced, not just documented —
  constructing a violating instance and asserting it raises.
- **Integration** (`tests/integration/test_document_processor.py`):
  full round trip for PASS (no conflict) and INCONCLUSIVE (conflict)
  outcomes with correct `parent_evidence_result_ids` lineage and
  `HIGHLY_SENSITIVE` encryption-boundary checks (mirrors
  `test_ocr_full_round_trip_covers_every_outcome_state`); ambiguous-
  capture short-circuit extended to the new stage; tenant isolation
  extended (wrong-tenant + concurrent-cross-tenant, mirroring HV-012's
  additions); 6-way partial-stage independence; exception-taxonomy
  propagation (a buggy reconciler's exception must propagate uncaught,
  same as every other stage); policy-visibility end-to-end test driven
  by `DOCUMENT_FIELD_EXTRACTION`'s canonical fields; **a dedicated
  freshness test**: persist a reconciliation, retry a parent stage to a
  different outcome (e.g. OCR `UNAVAILABLE` → real retry), re-run
  `process()`, and assert the `DOCUMENT_FIELD_EXTRACTION` row is
  recomputed (new `parent_evidence_result_ids`, not the stale set) rather
  than reused — this is the test that proves DP-008 §4's principle is
  actually implemented, not just described.
- **HV-013** (once this phase implements and validates cleanly): hostile
  validation of the reconciliation surface specifically — adversarial
  field values (Unicode, control characters, mirroring HV-012's OCR
  coverage since reconciliation consumes OCR's own adversarial output),
  conflict-detection false-positive/false-negative boundary cases
  (including §7.1's FAIL-as-input rule attacked directly: a checksum-
  failed MRZ read deliberately crafted to agree with OCR, and separately
  to disagree, confirming both paths behave as §7.1 specifies), the §4
  normalization-symmetry invariant attacked directly (the same raw value
  fed in via different sources must never produce a spurious agreement
  or disagreement purely because of which source carried it), and
  confirmation `DOCUMENT_FIELD_EXTRACTION` never reaches `FAIL` (no code
  path produces it, per §5.3's status logic having exactly two branches).

---

## 10. Explicit non-goals

Carried forward from DP-008 §7, restated for implementation-plan
precision:

- No real normalization/comparison library (date parsing, fuzzy name
  matching) — the deterministic baseline (§4) stays intentionally
  minimal, same discipline as Phase 1-3's own deterministic stand-ins.
- No document-type-specific field-mapping registry — a fixed per-source
  mapping is sufficient until a real adapter exists (§4).
- No `IdentityConsistency` or `DocumentAuthenticity` work (DP-001's own
  distinct future items, untouched).
- No Decision Engine changes — `GateKind.CONFLICT` already exists and
  needs no modification (DP-008 §2.7/§3.8).
- No field-level provenance storage (`field_sources`) — DP-008 §3.4's
  conditional decision stands as-is.
