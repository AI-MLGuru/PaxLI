# DP-008 — Document Processing Phase 4 Discovery (`DOCUMENT_FIELD_EXTRACTION` + Cross-Source Reconciliation)

**Status: FROZEN.** Three reconciliation passes plus a final consistency
sweep; every discovery question resolved (FROZEN or SELECTED), nothing
left OPEN (§9). Mirrors DP-001/DP-003/DP-005's process: a full spec
trace plus a full repository inventory, followed by discovery answers
reconciled across three rounds. Nothing here is authorized for
implementation — no production code has been read for the purpose of
changing it, only for the purpose of understanding current state; that
begins with DP-009, not this document. §6 records one narrow, explicit
amendment to DP-001 Decision 7 — surfaced by discovery, not silently
assumed — still to be applied to `DP-001-document-processing-discovery.md`
itself as a separate, subsequent step; deliberately not done in this
commit.

**Depends on:** `docs/decisions/DP-001-document-processing-discovery.md`
(Decisions 2, 5, 7 in particular — all FROZEN), `docs/decisions/DP-003-document-processing-phase-2-discovery.md`
(Decision 11, deferring this work), `docs/decisions/DP-005-document-processing-phase-3-ocr-discovery.md`
(Decision 0/11, deferring it again), `docs/decisions/DP-007-document-processing-phase-3-closure.md`
(the pointer that opened this discovery).

---

## 0. A naming discrepancy, surfaced rather than silently absorbed

This session (both of us) has been calling this work "Phase 4." But
`docs/decisions/DP-001-document-processing-discovery.md:551-561` (§17,
"Proposed implementation phases") already used that exact number for
something else:

> **Phase 2** — Field-schema and document-catalog decisions land... plus
> `DOCUMENT_FIELD_EXTRACTION` reconciliation across their outputs...
>
> **Phase 3** — Real adapter for at least one capability (most likely OCR)...
>
> **Phase 4** — `IdentityConsistency`, once Open Question 5 (its
> inputs/algorithm) is settled.

Neither DP-001's original "Phase 2" (reconciliation, bundled with
MRZ/Barcode implementation) nor its "Phase 3" (a *real* adapter,
replacing a deterministic stand-in) matches what actually happened:
actual Phase 2 became MRZ+Barcode only (reconciliation explicitly carved
out, DP-003 Decision 11), actual Phase 3 became OCR but stayed a
deterministic stand-in (not the "real adapter" DP-001 envisioned), and
this document's "Phase 4" is `DOCUMENT_FIELD_EXTRACTION` reconciliation —
which is DP-001's **Phase 2** content, not its Phase 4. DP-001's actual
"Phase 4" (`IdentityConsistency`) hasn't been reached at all.

This doesn't need to block anything — the *phase numbers* are just
session-local implementation-order labels (`DP-002`, `DP-004`, `DP-006`
already track real chronology, not DP-001's original sketch), and this
document's own number (`DP-008`) is unambiguous regardless of what
colloquial name we use for it in conversation.

**Decision: FROZEN.** We continue calling this Phase 4. The precise
framing, preserving historical truth rather than rewriting it: **DP-001
§17 is superseded as an implementation-order sketch by subsequent frozen
decisions and actual execution chronology** — not "wrong," just overtaken
by DP-003's and DP-005's explicit deferrals and by what was actually
built:

```text
DP-001 original sketch
        |
DP-003 explicitly defers reconciliation
        |
Phase 2 = MRZ + Barcode
        |
DP-005 explicitly defers reconciliation again
        |
Phase 3 = OCR
        |
DP-007 closes Phase 3
        |
Phase 4 = DOCUMENT_FIELD_EXTRACTION + reconciliation
```

---

## 1. Spec trace — normative anchors

Full detail in the research transcript; load-bearing findings below,
verbatim where it matters.

### 1.1 `DOCUMENT_FIELD_EXTRACTION` itself

The spec contains **exactly one** textual anchor for this evidence type
in its entire normative body — the taxonomy tree,
`docs/specification/part-03-evidence-semantics.md:99-105`:

```
Evidence
|- Capture: SelfieCapture, DocumentCapture
|- Document: DocumentQuality, DocumentClassification, OCRExtraction,
|            DocumentFieldExtraction, MRZ, Barcode/QR, DocumentAuthenticity
...
```

No dedicated section exists (unlike `NOT_REQUIRED` §3.19,
`INCONCLUSIVE` §3.22, or Evidence Conflicts §3.25). EVD-3.5.2 ("Evidence
types MUST have defined semantics before being accepted by the Decision
Engine") is currently unsatisfied for this type — this discovery
document, once reconciled, is what satisfies it. It is also **absent**
from Part IX's deferred-capability baseline (§9.33) and Part III's own
deferred list (§3.33) — neither confirmed in-scope nor deferred. It sits
in a genuine specification gap, not a documented decision either way.

### 1.2 EVD-3.25 — Evidence Conflicts (verbatim)

`docs/specification/part-03-evidence-semantics.md:393-404`:

> Evidence may disagree, such as `FaceMatch = PASS` with
> `IdentityConsistency = FAIL`. Conflicts MUST NOT be resolved through
> implicit precedence. Conflict semantics belong to the Decision Engine
> and applicable policy.
>
> - **EVD-3.25.1** Conflicting evidence MUST remain individually observable.
> - **EVD-3.25.2** A component MUST NOT silently overwrite contradictory evidence.
> - **EVD-3.25.3** Conflict resolution MUST be defined by Decision Engine policy.
> - **EVD-3.25.4** Unresolvable conflicts MUST produce a safe non-verifying decision such as `INCONCLUSIVE`.

### 1.3 DEC-5.22 — Conflict Resolution (verbatim)

`docs/specification/part-05-decision-engine.md:344-354`:

> Conflicting evidence, such as `FaceMatch = PASS` with `IdentityProvider
> = MISMATCH`, MUST be resolved by policy rather than arbitrary
> implementation precedence.
>
> - **DEC-5.22.1** Conflicts MUST NOT be resolved through arbitrary precedence.
> - **DEC-5.22.2** A policy-defined blocking conflict MUST prevent `VERIFIED`.
> - **DEC-5.22.3** A material conflict that policy cannot safely resolve MUST produce `INCONCLUSIVE`. `REVIEW_REQUIRED` is permitted only when the active policy explicitly defines the conflict as a human or downstream adjudication condition.

**DP-005's finding is confirmed directly, with full text now in hand**:
both worked examples (`FaceMatch`/`IdentityConsistency`,
`FaceMatch`/`IdentityProvider`) are cross-*domain* — a Biometric-type
evidence type disagreeing with an Identity/External-type evidence type.
Zero worked examples anywhere in the spec address same-field,
cross-*source* disagreement (OCR's `date_of_birth` vs. MRZ's
`date_of_birth` on the same capture) — the exact shape Phase 4 exists to
handle. This is a genuine gap, not settled precedent we can just follow.

### 1.4 Invariant 02 §2.5 and Invariant 01 (verbatim, relevant parts)

`docs/specification/part-02-architectural-invariants.md:127-147`:

> If the Decision Engine cannot produce a valid deterministic decision
> from a valid policy and evidence set, it MUST NOT produce `VERIFIED` or
> `REJECTED`; it MUST produce `INCONCLUSIVE`.
>
> - **2.5** Unresolved conflicting evidence MUST result in `INCONCLUSIVE`.

`docs/specification/part-02-architectural-invariants.md:98-117` (Invariant 01):

> No component outside the Decision Engine may declare a final
> verification verdict... Intelligence components MUST produce evidence
> or component-level outcomes rather than final verification verdicts.
> This includes face matching, document analysis, OCR, document
> authenticity, identity consistency...

Note "document analysis" is explicitly named — a field-reconciliation
component is exactly this kind of intelligence component, bound the same
way OCR/MRZ/Barcode already are.

### 1.5 EVD-3.17 — Evidence Relationships (the lineage primitive)

`docs/specification/part-03-evidence-semantics.md:294-304`:

> Evidence MAY reference other evidence. Derived evidence MUST remain
> distinguishable from source evidence. Typical lineages include capture
> to quality to OCR to identity consistency...
>
> - **EVD-3.17.1** Derived evidence MUST identify source evidence where lineage affects interpretation.
> - **EVD-3.17.2** Evidence lineage MUST NOT create circular dependencies that cannot be deterministically resolved.
> - **EVD-3.17.3** Deleting source evidence MUST NOT leave derived evidence falsely appearing fully reconstructible.

This is written for *derivation* (A produces B), not *reconciliation of
concurrent siblings* (A, B, C independently observe the same fact and
must be merged) — the closest available primitive, not an exact fit.
Worth naming as a gap rather than silently stretching it to cover
something it wasn't written for.

### 1.6 Provenance — EVD-3.8 and EVD-3.34 (object-granular, not field-granular)

`docs/specification/part-03-evidence-semantics.md:162-189` (§3.8) and
`:574-601` (§3.34, the normative evidence object) both establish
provenance at the *evidence-object* level (`producer`, `producer_version`,
`model_reference`, `source_reference`, `parent_evidence_ids[]`). **There
is no field-level, per-attribute provenance construct anywhere in the
spec** — nothing that would let a reconciled result say "this
`date_of_birth` value came from MRZ, that `document_number` came from
OCR." This is a genuine design choice Phase 4 must make (see §3.4 below),
not one the spec settles for us.

### 1.7 What a reconciliation component may assert

`docs/specification/part-03-evidence-semantics.md:17,496,500`:

> Models and verification components produce evidence. The Decision
> Engine interprets evidence and produces the final verification
> decision. Evidence MUST NOT itself constitute a final verification
> verdict.
>
> A component MUST NOT directly return `REJECTED` or `VERIFIED`... **EVD-3.30.1** Only the Decision Engine may produce the final verification verdict.

Combined with EVD-3.25's "conflict semantics belong to the Decision
Engine and applicable policy" — this capability may combine, normalize,
and flag disagreement; it may never itself decide what a disagreement
*means* for the session outcome.

---

## 2. Repository inventory — current state

### 2.1 `DOCUMENT_FIELD_EXTRACTION` is a genuine, confirmed blank slate

Every one of the 13 repo hits for the literal string
`DOCUMENT_FIELD_EXTRACTION` outside the spec is either (a) static
registry/classification wiring, (b) a docstring forward-reference to
"Phase 4," or (c) a test proving the type is currently **untouched** —
most pointedly `tests/integration/test_document_processor.py:1401-1431`'s
`test_ocr_processing_never_writes_document_field_extraction`, which
asserts the row is `None` after a full real pipeline run. **Zero
production code path reads or writes this evidence type today.**

### 2.2 The code-level placeholder schema does not match DP-001's own frozen Decision 7

Current code, `core/evidence_result/schemas.py:53-55`:

```python
class DocumentFieldExtractionResult(BaseModel):
    fields: dict[str, str]
```

But DP-001 Decision 7 (FROZEN, `docs/decisions/DP-001-document-processing-discovery.md:535-545`)
already specifies a hybrid schema:

> Canonical fields: `full_name`, `surname`, `given_names`, `date_of_birth`,
> `sex`, `document_number`, `nationality`, `expiry_date`. Canonical fields
> not applicable to a document type, or whose decomposition cannot be
> reliably established from the source, are `null` rather than omitted or
> empty-stringed. `extensions: dict[str, str]` preserves document-specific
> fields outside the canonical vocabulary and is NOT directly addressable
> by Decision Engine policy conditions in V1.
>
> When both `full_name` and `surname`/`given_names` are populated for the
> same result, the (still-unresolved) reconciliation algorithm MUST
> derive them consistently from the same normalization pass — they must
> not be independently reconciled and left free to diverge.

**This is a real, pre-existing discrepancy between a frozen decision and
current code** — not something Phase 4 discovery needs to re-decide, only
something the eventual implementation plan needs to close. Flagging it
here so it isn't lost.

### 2.3 `parent_evidence_result_ids` — fully built, fully validated, zero real callers

`core/evidence_result/models.py:54`: `parent_evidence_result_ids:
tuple[UUID, ...] = ()`. Wired end-to-end: service-layer cross-tenant
validation (`core/evidence_result/service.py:279-297`, real logic, real
test coverage at `tests/integration/test_evidence_result_tenant_lineage_boundary.py:152,184`
and `tests/unit/test_evidence_result_service.py:451,476`), ORM column,
migration, repository serialize/deserialize. **No production code path
supplies a non-empty value anywhere** — `infrastructure/document/processor.py`'s
`_persist_stage` doesn't even accept the parameter today. This field was
evidently built ahead of need, anticipating exactly this phase (DP-001
itself names it: *"parent_evidence_result_ids spanning OCR/MRZ/barcode
per Decision 2"*). Phase 4 would be its first real caller.

### 2.4 The three existing extractions share one shape — and it's not the canonical one

`core/document/types.py`:

```python
class OCRExtraction:     raw: str; fields: dict[str, str]
class MRZExtraction:     raw: str; fields: dict[str, str]
class BarcodeExtraction: raw: str; fields: dict[str, str] = {}; symbology: str | None = None
```

All three are flat, unstructured, string-keyed maps with **no shared key
vocabulary** (each capability invents its own field names independently),
no per-field confidence, and no cross-referencing to a canonical
attribute set. A reconciler consuming all three has to key-match across
three independently-chosen vocabularies with nothing in code today
anchoring them to DP-001 Decision 7's canonical field list.

### 2.5 The capability pattern — and why reconciliation may not fit it as-is

`core/document/capabilities.py` establishes one consistent shape: a
narrow single-method `ABC`, taking `image: bytes` (never a persistence
identifier — the module docstring is explicit: *"A capability MUST NOT be
passed persistence identifiers... only the domain-level value it
needs"*), returning a pure `core.document.types` dataclass. Every
existing capability is this shape. A field reconciler is structurally
different: its inputs are the *outputs* of three sibling stages, not raw
image bytes, and there is no "real adapter" that could ever be swapped
in behind a port the way an ML-based OCR engine eventually could be —
reconciliation is pure logic/algorithm, not a model or external system.
Whether it should be shaped as a capability Protocol anyway (for
consistency) or as `DocumentProcessor`-internal orchestration logic (no
port, because there is genuinely nothing to swap) is a live fork — see
§5.

### 2.6 The pipeline has no existing hook for this stage, but a clean seam to add one

`infrastructure/document/processor.py`'s `process()` runs five stages
strictly sequentially: quality → classification → mrz → barcode → ocr.
No stub method, no `# TODO: Phase 4` marker, no unused constructor
parameter exists — the constructor takes exactly the five existing
capabilities. But the established pattern (outcome-map dict,
`_persist_stage`, `_is_reusable`, per-stage fresh session, the ambiguous-
capture precondition) is fully generalizable to a sixth stage with no
structural surprise expected.

### 2.7 The Decision Engine's conflict machinery already exists, downstream

`core/policy/gates.py` already has a `GateKind` enum with `BLOCKING` and
`CONFLICT` members, a validator defaulting a `CONFLICT`-kind gate's
reason code to `ENGINE:UNRESOLVED_EVIDENCE_CONFLICT`
(`core/decision/enums.py:56`), and evaluator logic
(`core/decision/evaluator.py:223,257-258`) distinguishing a policy
author's explicit recognition of a conflict shape from an engine-invented
heuristic. **This means Phase 4's evidence-producer side doesn't need to
invent new decision-layer plumbing.** It needs to produce a
`DOCUMENT_FIELD_EXTRACTION` `EvidenceResult` (with fields, and some
signal that a conflict occurred) that a policy author can reference via
an ordinary `EvidenceCondition`, exactly like any other evidence type —
the `CONFLICT`-kind gate already exists to receive it.

### 2.8 `DOCUMENT_AUTHENTICITY` / `IDENTITY_CONSISTENCY` — also taxonomy-only

Both are enum members with schema-registry placeholders and classification
entries, but **zero** producing capability, protocol, or `DocumentProcessor`
stage. `IdentityConsistencyResult` already has a shape —
`consistent: bool, mismatched_fields: tuple[str, ...] = ()`
(`core/evidence_result/schemas.py:72-74`) — that reads as if it was
sketched to consume `DOCUMENT_FIELD_EXTRACTION`'s eventual reconciled
output (comparing it against, presumably, an external identity claim or
provider response), but no code anywhere establishes that relationship.
Worth naming as context, not something Phase 4 needs to resolve — it's
DP-001's own "Phase 4" (§0 above), a later, separate discovery.

---

## 3. The discovery questions

The original ten, plus two more surfaced during reconciliation (§3.11,
§3.12). Each is marked FROZEN, SELECTED, or OPEN below (§9 summarizes the
final state across three reconciliation passes).

### 3.1 What exactly `DOCUMENT_FIELD_EXTRACTION` is responsible for

**Decision: FROZEN, terminology tightened.** The original draft's
"cross-source-reconciled representation" phrasing is corrected — "
reconciled" can accidentally imply the component *resolves* conflicts,
which it must not do. The precise responsibility: producing a
**canonicalized and conflict-aware** representation of a document
capture's identity fields (DP-001 Decision 7's schema), by mapping each
source's independently-produced `fields: dict[str, str]` vocabulary onto
the canonical attribute set, normalizing comparable values, determining
agreement/disagreement per source, and preserving — never silently
collapsing — observed conflict.

Concretely, given:

```text
OCR:     date_of_birth = 2005-04-12
MRZ:     date_of_birth = 2005-04-12
Barcode: date_of_birth = 2004-04-12
```

the component may conclude:

```text
date_of_birth: value = ?, conflict = true
```

It must **not** conclude:

```text
MRZ wins, therefore date_of_birth = 2005-04-12
```

— not without a separately, explicitly frozen source-authority rule,
which does not exist today and is not implicitly created by this
document.

`DOCUMENT_FIELD_EXTRACTION`:

- canonicalizes source fields (maps source-specific vocabulary to the
  canonical attribute set)
- normalizes comparable values before comparison
- determines agreement/disagreement per canonical field
- preserves observable conflict
- produces canonical field values where deterministically justified
  (agreement, or a single present source)
- leaves unresolved conflict visible, never silently picked

It does **not**:

- authenticate the document (DP-001 Decision 6, deliberately
  unimplemented)
- establish identity or compare against an external identity claim
  (DP-001's own distinct "Phase 4," `IdentityConsistency` — a separate
  future discovery)
- select the "truth" among contradictory sources absent an explicit,
  separately frozen authority rule
- produce a verification decision, or decide what a detected conflict
  means for the session's final outcome (Decision Engine/policy
  territory, per EVD-3.25/DEC-5.22 — §2.7 already provides the
  downstream mechanism)

### 3.2 What it consumes from OCR / MRZ / Barcode

This splits into two separable questions.

**A. What is the logical input? Decision: FROZEN.** `DOCUMENT_FIELD_EXTRACTION`
consumes the effective outputs of OCR, MRZ, and Barcode/QR for the same
document capture — each source's extracted `fields`, plus enough outcome
state to distinguish usable evidence from absence, unreadability, and
unavailability (§3.7 depends on this directly: `UNAVAILABLE` is not
`UNREADABLE`, and neither is disagreement).

**B. Where does that input actually come from at runtime? Decision:
FROZEN, resolved by §5's selection.** Two legitimate shapes were on the
table:

```text
A) OCR extraction ---\
   MRZ extraction -----> reconciler -> EvidenceResult   (in-memory domain values)
   Barcode extraction -/

B) OCR EvidenceResult ---\
   MRZ EvidenceResult -----> reconciler -> EvidenceResult   (persisted rows)
   Barcode EvidenceResult -/
```

The original draft jumped straight to (B) without justifying why
persistence must be the boundary — and (B) is in tension with
`core/document/capabilities.py`'s own stated rule that a capability "MUST
NOT be passed persistence identifiers... only the domain-level value it
needs" (§2.5). §5 settles it as (A): the dedicated domain reconciler
takes in-memory domain values (`OCRExtraction | None` etc.);
`DocumentProcessor` is the one component that reads persistence, and
supplies the reconciler with already-fetched domain values, exactly as
it already does for every other stage's effective-result check.

### 3.3 What the canonical document-field schema should be

**Decision: FROZEN — already answered by DP-001 Decision 7.** Not
re-opened here:
`full_name`, `surname`, `given_names`, `date_of_birth`, `sex`,
`document_number`, `nationality`, `expiry_date`, plus a non-policy-
addressable `extensions: dict[str, str]`. What Phase 4 discovery must
establish are the **semantic rules** Decision 7 explicitly left open
(normalization, conflict resolution, name-component derivation — quoted
in full in §2.2 above); their concrete *algorithm* (the actual
comparison/normalization implementation) is DP-009 (implementation plan)
territory, not this document's. Closing the gap between the frozen
schema and the current `fields: dict[str, str]` code placeholder is also
implementation work, not a discovery question.

### 3.4 How source provenance is represented

Two separable questions, resolved differently.

**Object level — Decision: FROZEN direction.** Which OCR/MRZ/Barcode
rows fed this result: use `parent_evidence_result_ids` (§2.3) — its
first real caller, exactly the shape DP-001 anticipated. Structurally
free; no new mechanism needed.

**Field level — Decision: SELECTED (conditional), resolved in Pass 2.**
No separate `field_sources` structure in V1, **provided** the following
condition holds and is treated as a standing requirement, not a one-time
justification:

> Given the immutable parent evidence (`parent_evidence_result_ids`) and
> the immutable, versioned reconciliation algorithm (`producer` +
> `producer_version`), the exact canonical output and conflict state for
> every field MUST be deterministically reconstructible.

Concretely this requires: (1) parent evidence IDs (already frozen,
§2.3/object level above), (2) a genuinely deterministic algorithm — same
inputs always produce the same output, no hidden randomness or wall-clock
dependence, (3) `producer`/`producer_version` recorded on the result
(already part of `EvidenceResult`, §2.9), (4) explicit conflict state
recorded per field (§3.5/§3.12), and (5) enough output information that
replaying the algorithm against the named parents reproduces the
persisted result exactly. If all five hold, "why does `date_of_birth`
say 1999-01-01" is answerable by re-running the (versioned, deterministic)
algorithm against the three named parent rows — a real, sufficient audit
path — without needing a separate stored `field_sources` map. This is a
conditional decision, not "we don't need it": if a future implementation
can't actually guarantee determinism (e.g. reconciliation ever needs
non-deterministic tie-breaking), this decision must be revisited, not
silently kept.

**Written as an explicit, checkable invariant, finalized in Pass 3** (not
left as the vaguer "deterministic reconstructibility" phrasing above):

> Field-level provenance does not require a duplicated `field_sources`
> structure in V1. For any conflicted field (§3.5), the contributing
> source observations MUST remain reconstructible from the immutable
> parent evidence results, their producer/version metadata, and the
> versioned deterministic reconciliation algorithm:
>
> ```text
> conflicted_fields
>         +
> parent_evidence_result_ids
>         +
> immutable parent evidence
>         +
> producer/version information
>         +
> deterministic reconciliation algorithm/version
>         |
>         v
> reconstructible source observations
> ```
>
> e.g. `date_of_birth` conflicted → `{MRZ: 2005-03-14, OCR: 2005-03-15}`
> is recoverable by replaying the algorithm against the two named parents,
> without that pairing ever being separately stored. **If this
> reconstruction guarantee cannot be maintained, the no-`field_sources`
> decision is invalid** and must be revisited, not silently kept.

### 3.5 How conflicts are represented without silently overwriting evidence

**The "never silently overwrite" half — Decision: FROZEN, satisfied by
construction.** Reconciliation produces a *new* `DOCUMENT_FIELD_EXTRACTION`
row; it never touches, mutates, or supersedes the OCR/MRZ/Barcode rows
themselves (same immutability discipline enforced everywhere else in this
codebase). EVD-3.25.1/3.25.2 are satisfied by construction, not by
anything Phase 4 needs to newly build.

**How the row itself represents a conflict — Decision: FROZEN, finalized
in Pass 3.** The risk ruled out explicitly along the way: collapsing
*one* field-level disagreement into the *entire* result going
`INCONCLUSIVE` in a way that destroys visibility into the fields that
*did* agree —

```text
one conflict anywhere
        |
entire DOCUMENT_FIELD_EXTRACTION = INCONCLUSIVE, no field data
```

— is rejected. Mechanism: a new field on `DocumentFieldExtractionResult`,
`conflicted_fields: tuple[str, ...] = ()`, naming which of the eight
canonical fields (never `extensions` keys — those stay non-policy-
addressable per Decision 7, unchanged) are currently nulled specifically
because of source disagreement. Given:

```text
full_name       agreement
date_of_birth   conflict
sex             agreement
nationality     agreement
```

the result carries `full_name`, `sex`, `nationality` as populated values,
`date_of_birth = null`, and `conflicted_fields = ("date_of_birth",)` —
not a row emptied of everything just because one field disagreed.

**The governing invariant is one-directional, and this direction matters:**

> A field listed in `conflicted_fields` MUST be `null`. A canonical field
> being `null` does **not** imply it is listed in `conflicted_fields`.

i.e. `conflicted_fields contains X ⟹ X == null`, but not the converse —
because Decision 7 already intentionally uses bare `null` for
not-applicable and undecomposable cases (§3.12), and those must not be
misread as conflicts.

Full semantics of `conflicted_fields`, frozen together as one unit:

- contains only names drawn from the eight canonical fields, never
  `extensions` keys;
- a listed field MUST have a `null` canonical value;
- a non-empty tuple indicates unresolved source disagreement for exactly
  those fields;
- it does **not** identify an authoritative source (§3.9's
  canonicalization-vs-authority-selection boundary applies here
  directly);
- it does **not** resolve the conflict — it is an observability signal,
  not a policy verdict;
- it does not alter the semantics or non-addressability of `extensions`;
- ordering is deterministic (same conflicted set always serializes the
  same way);
- empty means no currently detected canonical-field conflict.

**Two-tier model, now schema-concrete:**

```text
Source observations
       |
Canonicalization
       |
Conflict detection
       |
+-------------------------------------+
| DocumentFieldExtractionResult        |
|                                       |
| canonical fields (8, per Decision 7) |
| conflicted_fields                    |
| extensions                           |
+-------------------------------------+
       |
EvidenceResult
       |
       +-- PASS                    (conflicted_fields == ())
       +-- INCONCLUSIVE            (conflicted_fields != ())
           + FIELD_VALUE_CONFLICT
```

Non-empty `conflicted_fields` → `status = INCONCLUSIVE`,
`reason_codes` includes a new `FIELD_VALUE_CONFLICT`-style code
(following `core/document/reason_codes.py`'s established bare-name
convention — exact enum member name is DP-009 territory). This preserves
every non-conflicting canonical value, the fact that a specific field
cannot safely be asserted, the identity of the conflicting field(s), and
the overall conflict state — without ever claiming a resolution occurred.
See §6 below: this mechanism requires a narrow, explicit amendment to
DP-001 Decision 7, not a silent extension of it.

### 3.6 Which source combinations are applicable to which document types

**Decision: FROZEN, with an important correction to how this question is
usually framed.** `DocumentProcessor` invokes MRZ/Barcode/OCR
*unconditionally* on every classified `DOCUMENT` capture today — DP-003
Decision 7 (quoted in `infrastructure/document/processor.py:205-210`)
deliberately established no branching on `DOCUMENT_CLASSIFICATION`'s
result to skip stages. So applicability isn't pipeline-gated by document
type; it's *emergent* — a passport naturally has no barcode payload to
decode (→ `BARCODE_QR = NOT_SUBMITTED`), a `NIN_SLIP` naturally has no
MRZ zone (→ `MRZ = NOT_SUBMITTED`). DP-001 Decision 5 only mandates that
`ICAO_PASSPORT_DATA_PAGE` MUST support the MRZ path; it neither forbids
barcode on a passport nor mandates/forbids barcode on `NIN_SLIP`
variants. **This reframes the actual question Phase 4 needs to answer**:
not "which sources apply to which document type" (that's already emergent
from existing per-stage behavior) but "how does reconciliation treat a
sibling stage that is `NOT_SUBMITTED`/`UNREADABLE`/`UNAVAILABLE` rather
than `PASS`" — see §3.7, which is the real question underneath this one.

### 3.7 What constitutes agreement, disagreement, absence, and insufficient evidence

**Decision: FROZEN conceptually; concrete comparison algorithm deferred
to DP-009.** The semantic contract of normalization belongs in discovery
even though its implementation doesn't — without it, "agreement" isn't
actually defined. Two sources rendering a name as `"JOHN   DOE"` vs.
`"JOHN DOE"` are very likely the same value; `"01/02/2000"` vs.
`"02/01/2000"` are the same date only under a known interpretation rule;
`"O"` vs. `"0"` must **not** default to equal. So: **comparison MUST
operate on field-type-specific, canonically normalized values, never on
raw source strings** — this policy is frozen now; the concrete
normalization rules/library are DP-009 territory.

With that in place, the four states:

- **ABSENT**: no usable value exists from a given source for a given
  field. A sibling stage's effective result with
  `status ∈ {NOT_SUBMITTED, UNAVAILABLE}` (or, for OCR, `UNREADABLE` —
  OCR has no `NOT_SUBMITTED`, DP-005 Decision 3), or a `fields` dict with
  no key for that canonical attribute, both count as ABSENT for that
  field. **`UNAVAILABLE` is not equivalent to `UNREADABLE`, and neither
  constitutes disagreement** — this distinction matters and must not be
  collapsed. Not evidence of anything; must never be treated as
  disagreement with a present source (conflating "MRZ didn't run" with
  "MRZ disagreed" would fabricate a conflict where none exists).
- **INSUFFICIENT**: every source is ABSENT for a given field. The
  canonical field is `null` (Decision 7's own null-vs-omit rule); no
  conflict is raised — there's nothing to disagree about.
- **AGREEMENT**: one or more usable (non-ABSENT) sources produce the same
  canonical normalized value for a field. The field is populated, sourced
  (object-level lineage via `parent_evidence_result_ids`), no conflict.
- **DISAGREEMENT**: two or more usable sources produce different
  canonical normalized values for the same field. This is the real
  EVD-3.25/DEC-5.22 territory — represented per §3.5's two-level model.

### 3.8 How unresolved conflicts remain observable to the Decision Engine

**Decision: FROZEN — no new Decision Engine plumbing required, phrased
carefully.** §2.7: `core/policy/gates.py`'s `GateKind.CONFLICT` and
`EngineReasonCode.UNRESOLVED_EVIDENCE_CONFLICT` already exist. The
original draft's "purpose-built for exactly this" overstates it slightly
— the spec's own worked examples (§1.3) never establish this mechanism
was designed specifically for same-field, cross-source reconciliation;
it was built for cross-domain conflicts (`FaceMatch`/`IdentityConsistency`
etc.). The accurate framing: **existing Decision Engine conflict
machinery provides a sufficient downstream mechanism for
policy-controlled handling of conflicts, subject to Phase 4 producing an
explicit and policy-addressable conflict signal.** Phase 4's producer-side
job is only to make the disagreement *visible* in the persisted
`DOCUMENT_FIELD_EXTRACTION` row (per §3.5) — a policy author then writes
an ordinary `CONFLICT`-kind `Gate` with an `EvidenceCondition` against
it, and DEC-5.22.2/5.22.3 + Invariant 02 §2.5 govern the rest within
already-built Decision Engine code. No new Decision Engine architecture
is invented here.

### 3.9 What this capability is allowed to assert vs. what remains a Decision Engine concern

**Decision: FROZEN**, directly from Invariant 01/EVD-3.30/EVD-3.25's
preamble ("conflict semantics belong to the Decision Engine and
applicable policy"): this capability may assert (a) the canonical field
values it was able to derive, (b) which canonical fields it could not
populate from any source, and (c) which canonical fields had genuinely
disagreeing source values. It may never assert: which disagreeing value
is "correct," what a disagreement should mean for the session's outcome,
or a final verification verdict of any kind. This is the same boundary
every other capability in this codebase already respects (§1.7) — Phase
4 doesn't need a new rule, just faithful application of the existing one.

One subtlety worth stating explicitly, since it's easy to blur:
**choosing a deterministic normalized representation is not the same
thing as choosing which source is "correct."** Normalizing
`"01/01/2000"` (OCR) and `"2000-01-01"` (MRZ) to the same canonical
`2000-01-01` is legitimate canonicalization — both sources agree, only
their *formatting* differed. Choosing `2000-01-01` over MRZ's
`2001-01-01` because "MRZ is more reliable than OCR" is a **source-
authority decision** — a different, materially riskier kind of choice
that must never be embedded silently inside what looks like ordinary
normalization. If a source-authority rule is ever wanted, it must be its
own explicit, separately frozen decision, not something normalization
code does implicitly by picking whichever source happens to run last, or
happens to be first in a dict-merge.

### 3.10 How the capability interacts with existing evidence/persistence/policy architecture

**Decision: FROZEN, both sides — the input side resolved by §5.** Output
side: the result is persisted through the exact same
`EvidenceResultService.create()`/`supersede()` pattern every other stage
already uses, referencing its OCR/MRZ/Barcode parents via
`parent_evidence_result_ids` (first real use of already-built,
already-tested infrastructure — §2.3), classified `HIGHLY_SENSITIVE`
(already wired, `core/evidence_result/classification.py:44`), and
consumed by policy through an ordinary `EvidenceCondition` against
`DOCUMENT_FIELD_EXTRACTION`'s canonical top-level fields — `extensions`
stays non-addressable by policy per Decision 7, unchanged. No new
persistence mechanism, no new policy-evaluation mechanism, no new
encryption/classification mechanism needed on the output side.

Input side, resolved by §5's selection: the reconciler itself never reads
persistence. `DocumentProcessor` reads the three sibling effective
results (exactly as it already does for every other stage's own
effective-result check) and hands the dedicated domain reconciler
already-fetched domain values — `EvidenceResultService.get_effective_for_session_by_type()`
is called by `DocumentProcessor`, never by the reconciler.

### 3.11 How source-specific fields map to canonical fields

**Decision: SELECTED, resolved in Pass 2 once §5 selected the dedicated
reconciler.** The mapping belongs to the reconciler's domain boundary,
not to OCR/MRZ/Barcode. Reasoning: the source producers answer "what did
this source observe?" (`OCR: dob -> "1990/01/02"`, `MRZ: date_of_birth ->
"900102"`, `Barcode: birthDate -> "1990-01-02"`); the reconciler alone
answers "how does that observation correspond to our canonical document
vocabulary?" Coupling every producer to the canonical model (`OCR ->
canonical`, `MRZ -> canonical`, `Barcode -> canonical`, independently)
would coordinate three unrelated implementations against one shared
vocabulary for no benefit; keeping each producer emitting its own
natural vocabulary and letting the reconciler own the translation
(`OCR/MRZ/Barcode -> Reconciler -> canonical vocabulary`) is the cleaner
boundary and matches §3.1's framing of the reconciler as the one
component responsible for canonicalization. The concrete mapping
table/registry structure (per-source, or further split per document
type, since a `NIN_SLIP` OCR read and an `ICAO_PASSPORT_DATA_PAGE` OCR
read may use different vocabularies for the same capability) remains
implementation-plan (DP-009) territory — this decision settles only
*ownership*, not the mechanism.

### 3.12 Not-applicable vs. unavailable/unreadable/insufficient

**New question, added during Pass 1 — Decision: FROZEN, resolved in Pass
3.** DP-001 Decision 7's own text already collapses two of these cases:
"not applicable to a document type" and "decomposition cannot be
reliably established from the source" are both already just `null`,
undifferentiated, by the frozen decision itself — not something Phase 4
needs to invent a distinction for. Source-level execution state
(`UNAVAILABLE`/`UNREADABLE` on a given parent) is likewise already fully
represented on that source's own `EvidenceResult` and reconstructible via
`parent_evidence_result_ids` (§3.4) — the reconciled output doesn't need
to re-encode it. **No general per-field state machinery is added.**
`null` continues to mean exactly what DP-001 Decision 7 already says it
means. The one case that genuinely needed a new signal — because it's
the one case a normative rule (EVD-3.25.1) requires to remain observable,
and the one a bare `null` would otherwise silently discard — is
conflict, handled entirely by `conflicted_fields` (§3.5):

| Situation | Canonical field | Additional signal |
|---|---|---|
| Not applicable | `null` | none |
| Applicable, but no source can reliably establish it | `null` | none |
| A source is unavailable/unreadable | `null` or unaffected (depends on other sources) | reconstructible from that source's own parent `EvidenceResult` |
| Sources agree | canonical value | none |
| Sources disagree | `null` | listed in `conflicted_fields` |

This is a remarkably small surface area for the amount of ambiguity it
removes — one new field (§3.5), not five new states.

---

## 4. Derived-result reuse/invalidation on parent change

**Decision: FROZEN as a semantic principle in Pass 2; mechanism deferred
to DP-009.** Not one of the original ten questions, but structurally
required by precedent (DP-003 Decision 9, DP-005 Decision 9): once a
`DOCUMENT_FIELD_EXTRACTION` row is persisted, is it reusable/terminal on
retry the same way every other stage's result is? The original draft
proposed "yes, unconditionally, following the established pattern
exactly" — **that default did not survive reconciliation.** Every prior
stage that pattern applies to is *independent*: MRZ's own terminal state
depends only on MRZ's own row. `DOCUMENT_FIELD_EXTRACTION` is different
in kind — it is **derived from** OCR/MRZ/Barcode, not independent of
them, and EVD-3.17.1 already requires derived evidence to identify source
evidence "where lineage affects interpretation." Concretely:

```text
OCR v1 = UNAVAILABLE
MRZ v1 = VALID
Barcode v1 = VALID
        |
reconciliation v1 (built from OCR v1/MRZ v1/Barcode v1)

--- OCR retries ---

OCR v2 = VALID

current parents: OCR v2, MRZ v1, Barcode v1
current reconciliation: still built from OCR v1
```

Blindly inheriting independent-stage reuse semantics here produces a
**real correctness problem** — a persisted `DOCUMENT_FIELD_EXTRACTION`
row silently drifting out of sync with its own current parent set,
observable to policy as if it reflected OCR v2 when it does not. This is
not an accepted limitation to note in passing; it needed its own decision,
now settled at the semantic level:

> **Frozen principle: a `DOCUMENT_FIELD_EXTRACTION` result is reusable
> only when the effective parent evidence set it was derived from remains
> unchanged.** `DOCUMENT_FIELD_EXTRACTION`'s identity for reuse purposes
> is effectively `session + source evidence versions + reconciliation
> algorithm version`, not merely `session_id + evidence_type` the way
> every independent stage's identity is. If a parent is superseded
> (`OCR v1 -> OCR v2`), `reconciliation(OCR v1, MRZ1, Barcode1)` is not a
> valid stand-in for `reconciliation(OCR v2, MRZ1, Barcode1)` — reuse
> eligibility must account for the parent set, not just the row's own
> terminal status.

This principle is frozen now because it's an invariant Phase 4's design
must hold regardless of implementation; it does **not** yet decide *how*
invalidation is mechanically implemented — DP-009 chooses among (and this
list is illustrative, not exhaustive): comparing parent IDs at reuse
time, recomputing automatically whenever any parent's effective row
changes, explicitly superseding the derived result when a parent is
superseded, or deriving fresh from the current effective parent set on
every access with the persisted row treated as disposable/regenerable
rather than authoritative. Worth recording as one of Phase 4's own
invariants once an implementation plan exists, not just discovery prose.

---

## 5. The central architectural fork

Restating §2.5/§3.2 as its own item, since it's the one question that
changes the shape of everything else. The original framing was too
narrow — a straight binary between "shoehorn into the existing capability
pattern" and "no abstraction at all." There's a third, stronger option in
between that the first draft missed:

**Decision: SELECTED — dedicated domain reconciler.** Resolved in Pass 2
by testing the fork against four constraints rather than picking by
aesthetic preference:

1. **Not an image-processing capability.** Existing capabilities are
   `domain input (image) -> capability -> domain extraction/outcome`.
   Reconciliation is `domain observations -> reconciliation logic ->
   derived domain observation` — a genuinely different contract. Forcing
   it into the existing shape would make that abstraction less truthful,
   not more consistent. **Rules out option 1.**
2. **Must not consume persistence objects.** The existing capability
   boundary deliberately keeps persistence identifiers out of the
   document domain layer (§2.5's module docstring). A reconciler taking
   `EvidenceResult` objects directly would make persistence part of the
   algorithm's domain contract — instead it takes
   `OCRExtraction | None`, `MRZExtraction | None`, `BarcodeExtraction |
   None` (plus whatever domain-level outcome state §3.12 settles),
   supplied by the application/processor layer after it does the
   persistence read. **Rules out the naive version of option 1 even
   further, and rules out option 3's natural tendency to reach for
   persisted state directly.**
3. **Not "every component needs a Protocol" reasoning.** The
   justification for a dedicated interface isn't abstraction for its own
   sake — it's that reconciliation is a coherent domain operation with
   its own contract, independent of persistence and independent of
   image-processing adapters, which makes it independently testable with
   a precise semantic boundary. No fictional `RealDocumentFieldReconcilerAdapter`
   needs to be imagined to justify this; there may never be one, and
   that's fine — unlike OCR/MRZ/Barcode, this was never going to have a
   real adapter regardless of shape.
4. **The processor should orchestrate, not implement reconciliation.**
   `DocumentProcessor` already owns running stages, capability
   availability, persistence, retries, and session boundaries. Folding
   field mapping, normalization, comparison, and conflict construction
   directly into it would make it responsible for orchestration *and*
   domain reconciliation at once, growing increasingly procedural.
   **Rules out option 3**, absent some undiscovered constraint that makes
   a separate domain boundary impractical (none found).

```text
                    DocumentProcessor
                           |
             +-------------+-------------+
             v             v             v
            OCR           MRZ          Barcode
             |             |             |
             +-------------+-------------+
                           |
                DocumentFieldReconciler
                     (pure domain)
                           |
                           v
             canonical + conflict-aware
                    field result
                           |
                           v
                  EvidenceResult
```

| Option | Decision |
|---|---|
| Existing capability Protocol | REJECTED |
| Dedicated domain reconciler | SELECTED |
| Processor-internal logic | REJECTED |

**Interface-completeness, resolved in Pass 3:** the reconciler's exact
input type was left open here because `OCRExtraction | None` etc. can't
by itself distinguish "not applicable," "unreadable," "unavailable," and
"no fields" — `None` alone collapses them. §3.12's resolution settles
this the same way it settles the output side: the reconciler doesn't need
its *input* type to carry that distinction either. Per-source ABSENT
status (§3.7) is enough to drive the reconciliation logic (agreement/
disagreement/insufficient), and *why* a given source was ABSENT stays
reconstructible from that source's own parent `EvidenceResult` (§3.4) —
never something the reconciler's own input contract needs to encode. §5
is now both architecturally decided and interface-complete.

---

## 6. DP-001 Decision 7 — narrow amendment (FROZEN here; not yet applied to DP-001)

**This section exists because discovery honesty requires it.** The
`conflicted_fields` mechanism (§3.5) is not something DP-001 Decision 7
already permitted — it is a genuine change to the `DocumentFieldExtractionResult`
container Decision 7 froze. This document will **not** claim otherwise.
The correct framing, arrived at in Pass 3: DP-008 identified a real
contract gap between Decision 7's canonical-field container and EVD-3.25's
mandatory conflict observability, unforeseen when Decision 7 was frozen
(DP-001 predates any conflict-handling design for this evidence type).
The response is a **surgical, narrowly bounded amendment**, not an
architectural redesign and not a reopening of Decision 7's substantive
content.

**What this amendment does NOT touch** — explicitly, so scope creep can't
hide inside it: the eight canonical field names, their types, or their
meanings; the `extensions` mechanism or its non-policy-addressability;
the null semantics Decision 7 already establishes for not-applicable and
undecomposable fields; the canonicalization responsibility (§3.1); any
question of source authority (§3.9 — this amendment explicitly does not
introduce one); or the overall evidence model.

**What it does:**

> **DP-001 Decision 7 amendment (via DP-008):** Add
> `conflicted_fields: tuple[str, ...] = ()` to the
> `DocumentFieldExtractionResult` contract, as the minimal observability
> mechanism required by EVD-3.25.1. Semantics as frozen in §3.5:
> contains only names from the eight canonical fields (never `extensions`
> keys); a listed field MUST have a `null` canonical value (not the
> converse — `null` alone never implies conflict); a non-empty tuple
> indicates unresolved source disagreement for those fields only; it is
> an observability signal, not a policy verdict — it identifies neither
> an authoritative source nor a resolution; ordering is deterministic;
> empty means no currently detected canonical-field conflict.

**Process note for when this document freezes**: `docs/decisions/DP-001-document-processing-discovery.md`
itself should receive a short addendum to Decision 7 pointing at this
amendment (not a rewrite of Decision 7's own text) — so DP-001 remains
the record of what Decision 7 says today, with clear traceability to
where and why it changed, matching this project's own discipline that a
frozen decision changes only through an intentional, recorded decision,
never silently. Not done yet since DP-008 itself isn't frozen.

---

## 7. Explicit non-goals for this discovery round

Carried forward, not re-litigated:

- No normalization/comparison algorithm design (date parsing, name
  casing, fuzzy matching) — that's implementation-plan territory once
  the architecture here is settled.
- No `IdentityConsistency` design — DP-001's own distinct "Phase 4,"
  untouched by this document (see §0).
- No `DocumentAuthenticity` work — DP-001 Decision 6 stands, unchanged.
- No decision-layer changes — §2.7 confirms the `CONFLICT`-gate
  machinery already exists and needs no modification.

---

## 8. The core architectural insight this discovery round surfaced

Worth recording explicitly, since it reframes what Phase 4 actually is:
**`DOCUMENT_FIELD_EXTRACTION` is not "OCR + MRZ + Barcode glued
together."** It introduces a category of component PaxLI hasn't built
before —

```text
                RAW CAPTURE
                     |
        +------------+------------+
        |            |            |
       OCR          MRZ        Barcode
        |            |            |
        +------------+------------+
                     |
          DOMAIN RECONCILIATION
                     |
                     v
        DOCUMENT_FIELD_EXTRACTION
                     |
                     v
             DECISION ENGINE
```

The middle box is **derived-evidence generation from concurrent
siblings**, not the derivation-from-a-single-parent lineage EVD-3.17 was
actually written for (§1.5), and not the independent, parent-free
evidence production every capability built so far (quality,
classification, OCR, MRZ, barcode) performs. That's why two questions in
this document turned out more fundamental than the rest: **§3.5/§4**
(what a deterministic reconciliation actually means, field by field, and
how its result stays correctly tied to a parent set that can itself
change) matter more than whether the eventual class happens to live in
`capabilities.py`. This framing held throughout Pass 2 and Pass 3, and
should carry into DP-009: treat Phase 4 as introducing a genuinely new
component category, not a routine sixth pipeline stage.

---

## 9. Reconciliation status summary

| Area | State |
|---|---|
| Phase naming | FROZEN |
| Responsibility of `DOCUMENT_FIELD_EXTRACTION` | FROZEN (terminology tightened) |
| Canonical schema (8 fields + `extensions`) | FROZEN by DP-001, amended narrowly — §6 |
| Logical inputs | FROZEN |
| Physical/input acquisition boundary | Resolved by §5 |
| Object-level provenance | FROZEN |
| Field-level provenance (no `field_sources`) | SELECTED, conditional on the reconstructibility invariant — §3.4 |
| Conflict representation (`conflicted_fields`) | FROZEN — §3.5 |
| Source applicability | FROZEN |
| Absence/agreement/disagreement semantics | FROZEN conceptually |
| Normalization semantics | FROZEN conceptually; algorithm deferred to DP-009 |
| Decision Engine interaction | FROZEN |
| Capability assertion boundary | FROZEN |
| No source-authority selection in reconciliation | FROZEN — §3.1/§3.9 |
| Persistence mechanism (output side) | FROZEN direction |
| Persistence mechanism (input/acquisition side) | Resolved by §5 |
| Derived-result reuse/invalidation | FROZEN as principle; mechanism deferred to DP-009 |
| Architectural abstraction | SELECTED — dedicated domain reconciler, §5 |
| Source-to-canonical field mapping | SELECTED — reconciler owns it, §3.11 |
| Not-applicable vs. unavailable/unreadable/insufficient | FROZEN — §3.12, resolved by `conflicted_fields` alone |
| DP-001 Decision 7 amendment | FROZEN in this document; DP-001's own file still needs its addendum once DP-008 freezes — §6 |

**Nothing remains OPEN.** Three reconciliation passes closed every
question this document set out to answer, including the two (§3.5,
§3.12) that were still coupled after Pass 2 — both resolved by the single
`conflicted_fields` mechanism and its accompanying narrow DP-001
amendment (§6). DP-008 is ready for a final consistency pass rather than
further discovery.

---

## Appendix — raw research

Two parallel Explore-agent research passes (spec trace; repository
inventory) back this document; their full output, including every grep
hit and file:line citation not reproduced above, is available in this
session's transcript and can be re-run or expanded on request — kept out
of this record itself to match DP-001/DP-003/DP-005's own stated
convention of navigability over raw-dump completeness.
