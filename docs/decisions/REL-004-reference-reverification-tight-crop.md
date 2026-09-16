# REL-004 — Reference Face Extraction Re-Verification Fails on Extractor-Generated Tight Crops

**Status:** OPEN — scoping only. This record exists to name the design
problem precisely and lay out the alternatives without selecting one
prematurely. No implementation is authorized by this record.

Follows directly from [REL-003](REL-003-reference-extraction-instrumentation.md)
§5, which localized the mechanism (REL-002's shared-instance-concurrency
hypothesis was tested and rejected; it is not the cause). This record
picks up where REL-003 stopped: REL-003 found *where* the discrepancy
lives; REL-004 scopes what, if anything, should change about it.

## 1. The problem, stated precisely

Reference face acquisition runs face detection twice, not once:

```text
Original document image
        |
Detector call #1 (InsightFaceDocumentFaceExtractor.extract_candidate)
        |
Face found (confirmed live: face_count=1, det_score=0.8659)
        |
Tight bbox crop + JPEG re-encode (quality 95, no margin)
        |
Detector call #2 (InsightFaceDetector.detect, the FACE_DETECTION_REFERENCE stage)
        |
No face found (confirmed live and in isolation, deterministically)
        |
FACE_DETECTION_REFERENCE = INCONCLUSIVE / DETECTION_NO_FACE
```

The system is not failing to find the person's face in the document
image. It is failing its own **second-order re-detection invariant**:
having already found and cropped a face, the pipeline requires the same
class of detector to find that face *again*, independently, in the
crop alone — and for at least one real, consenting-subject fixture,
that invariant does not hold, deterministically, for a documented and
mechanistically understood reason (tight, margin-free crops can fall
outside a detector's calibrated scale/context expectations).

This is confirmed reproducible without any PaxLI server involvement:
cropping `subject_a/Image_1.jpg` to exactly the bbox InsightFace itself
reported (`474,675 → 1024,1452`), re-encoding as JPEG q95 exactly as
`extract_candidate()` does, and re-running the same `FaceAnalysis`
instance on the resulting crop returns zero faces, every time.

## 2. What this is not

- Not a concurrency issue (REL-002, rejected by direct experiment).
- Not a storage, upload, or decode-path issue (REL-002/REL-003, ruled
  out by checksum and byte-level comparison).
- Not model or configuration drift between call sites (REL-003:
  identical `det_size`, identical instance family, identical array).
- Not evidence that the fixture is unusable or that the person's face
  is not detectable — detector call #1 found it cleanly, with a
  confidence score no different from any other clean detection this
  session.

## 3. Alternatives to evaluate — none selected

| Option | What changes | Main open question |
|---|---|---|
| **A — Crop padding** | Add a configurable margin around the detected bbox before re-encoding | Does contextual margin reliably fix re-detection, and by how much margin? |
| **B — Trust extractor detection** | Reuse `extract_candidate()`'s own successful detection/crop result instead of re-running detection | Is the second detection call providing independent evidentiary value, or is it redundant given the extractor already ran the same detector? |
| **C — Different second-pass configuration** | Change `det_size` or detection threshold specifically for the re-verification call | Can re-verification be made robust without changing crop semantics at all? |
| **D — Redesign the verification contract** | Reconsider why detection is repeated at all | Is a second, independent detector call architecturally necessary here, or an artifact of the reference and probe chains sharing low-level primitives (per `processor.py`'s own module docstring) without re-examining whether reference needs the same shape as probe? |
| **E — Combination** | e.g. padded crop *and* retained re-verification | Does defense-in-depth (both a better crop and an independent check) provide meaningful value over picking one? |

Deliberately not narrowed further here. Option B in particular deserves
scrutiny before defaulting to A (padding): if re-verification is meant
to catch cases where `extract_candidate()`'s own detection was wrong or
degenerate, padding a crop it already trusts doesn't obviously add
safety; if re-verification exists for an unrelated architectural reason
(e.g. producing quality/embedding evidence that legitimately needs its
own detection pass), that reason should be named explicitly before
choosing an implementation.

## 4. What must not change while this is open

Per the same discipline REL-001 §5 and REL-002 §5 already established:
no production code changes follow from this record. The frozen
Synthetic/Local E2E fixture mapping is not modified because of this
finding — the E2E checkpoint closes independently with its actual,
current result (see the checkpoint's own closure record), not by
substituting a fixture to force a different outcome.

## 5. Next boundary

A future discovery/implementation pass selects and scopes one of §3's
options (or a variant), including its own tests (a hostile-crop test
fixture, a same-image regression test) and its own conformance check
against Part IV/V's evidence-semantics requirements — not assumed from
this scoping record alone.
