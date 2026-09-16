# REL-003 — Temporary Diagnostic Instrumentation: Live Reference-Extraction Call

**Status:** CLOSED — success criterion (§3) answered, and the
instrumentation localized the actual mechanism one call site further
than expected (§5). Instrumentation added, used for one live retry, and
fully removed (`git diff` against the pre-instrumentation file is empty)
before this record was closed. Not an architecture decision; no
permanent behavior change was authorized by this record, and none was
made.

Follows directly from [REL-002](REL-002-shared-insightface-concurrency.md)
§7's residual uncertainty: every hypothesis testable from outside the
live server process (upload/storage corruption, decode-path difference,
model configuration difference, isolated nondeterminism, deliberate
concurrency) has been checked and ruled out, but what the live server
actually passed to `InsightFaceDocumentFaceExtractor.extract_candidate()`
at the moment of the real `DETECTION_NO_FACE` failures has never been
directly observed. This record authorizes exactly one thing: a temporary,
diagnostic-only logging addition at that exact call site, to close that
gap.

## 1. Scope and constraints

1. Narrowly scoped to the exact call inside
   `InsightFaceDocumentFaceExtractor.extract_candidate()`
   (`infrastructure/face/document_face_extractor.py`) — the one call site
   REL-002 could not observe directly.
2. Diagnostic only. No retries, no resizing, no fallback logic, no change
   to detection outcome, control flow, or return values. The only new
   runtime behavior is emitting log events and, to capture the worker
   thread's identity, wrapping (not altering) the existing
   `self._app.get(image_array)` call so it also returns
   `threading.get_ident()` from inside the same thread.
3. Privacy-safe. Logs metadata and cryptographic hashes only — never
   image pixels, crops, or embeddings. Consistent with this project's
   existing `log_stage_event` discipline
   (`infrastructure/observability/stage_logging.py`), though implemented
   as a separate, clearly-temporary logger rather than extending that
   shared, tested, permanent schema.
4. Temporary. Every added line is bounded by an explicit
   `REL-003 TEMPORARY DIAGNOSTIC` marker, grep-able, with a predefined
   removal point: as soon as this record's success criterion (§3) is
   answered.
5. Reversible. Lands as one small, isolated commit; removed in a
   separate commit once the evidence is captured, before any fix is
   designed.
6. Logging failures are swallowed (try/except around the diagnostic
   block only), matching `log_stage_event`'s own established pattern —
   observability must never be able to alter pipeline behavior, and
   especially must not turn a diagnostic-only change into a new failure
   mode for the exact capability under investigation.

## 2. Fields captured

Immediately before and after the real `self._app.get(image_array)` call:

| Field | Purpose |
|---|---|
| SHA-256 of the raw input `image` bytes | Correlate against a known evidence checksum (session/attempt identity, without threading session_id through the extractor's interface) |
| Array shape | Verify dimensions and channel layout |
| Array `dtype` | Detect unexpected input representation |
| Array `C_CONTIGUOUS` flag | Identify array-layout differences |
| SHA-256 of the decoded array's raw bytes (`.tobytes()`) | Compare the actual runtime input against the isolated diagnostic's array, byte for byte |
| `det_size` (constructor value) | Confirm runtime configuration |
| `id(self._app)` | Confirm which `FaceAnalysis` instance served the call |
| Thread identity (event-loop thread at call time, worker thread inside `asyncio.to_thread`) | Establish execution context |
| Face count / detection scores after the call | Distinguish a missing detection from an exception, and capture the actual result for direct comparison |

## 3. Success criterion

> Did the live server pass the same effective image representation and
> configuration to the extractor that the isolated diagnostic used?

- **If yes** (array bytes hash matches the isolated repro's, shape/dtype/
  contiguity/det_size all match): the discrepancy is not in what reaches
  the extractor. The investigation moves inside the InsightFace/ONNX
  execution boundary itself — a materially different, harder question,
  out of this record's scope.
- **If no**: the discrepancy is finally localized to the live call path
  — something between evidence storage and this call site produces a
  different effective input than every reconstruction attempted so far.
  That localizes the next investigation instead of leaving it open-ended.

## 4. Next boundary (as originally written)

Capture one more live failure (or success) under this instrumentation,
record the answer to §3 here, remove the instrumentation in a dedicated
commit, and only then decide the next investigation step. No fix is
authorized by this record.

## 5. Result

One retry (session `f7a47691-af40-40bb-94e2-707c79a2db93`, same fixture
pair, fresh server process with instrumentation live) reproduced the
same `FACE_DETECTION_REFERENCE=INCONCLUSIVE`/`DETECTION_NO_FACE` result —
now 3-for-3 in the live server, still 3-for-3 success in every isolated
repro. The captured diagnostic log for the instrumented call:

```json
{"image_sha256": "b0e9c98f...", "array_shape": [1986, 1489, 3],
 "array_dtype": "uint8", "array_c_contiguous": true,
 "array_bytes_sha256": "18d99059...", "det_size": [640, 640],
 "face_count": 1, "det_scores": [0.8659]}
```

**Answer to §3: yes.** `image_sha256` matches the session's own stored
evidence checksum exactly. `array_bytes_sha256` matches a ground-truth
hash computed from an independent isolated decode of the same file,
byte for byte. Shape, dtype, contiguity, and `det_size` all match the
isolated diagnostic exactly. And critically: **the instrumented call
itself found the face** — `face_count=1`, `det_score=0.8659`, identical
to every isolated repro. `InsightFaceDocumentFaceExtractor.extract_candidate()`
is exonerated; it is not the source of the discrepancy.

**The investigation moved one call site further, not into the ONNX/
InsightFace execution boundary as anticipated, but to a second,
independent detection call downstream.** Reading
`infrastructure/face/processor.py` (`BiometricProcessor`, lines
739–759): after `extract_candidate()` returns `VALID` with a cropped
face image (`identity.reference_artifact.image`), the
`FACE_DETECTION_REFERENCE` evidence result is *not* derived from that
successful detection. It is produced by a **second, independent** call —
`self._face_detector.detect(image)` (line 415), where `image` is the
already-cropped, JPEG-re-encoded (quality 95) face sub-image, not the
original document photo.

This was reproduced directly, with no server involvement, in one script:
running `FaceAnalysis.get()` on the full `Image_1.jpg` finds the face
(`bbox=(474, 675, 1024, 1452)`, `det_score=0.8659`); cropping to exactly
that bbox, re-encoding as JPEG q95 (mirroring `extract_candidate()`'s own
logic line for line), and running `FaceAnalysis.get()` again — same
instance, same `det_size`, same everything — on the resulting crop
returns **zero** faces. Deterministic, not probabilistic, and has
nothing to do with concurrency, storage, decode paths, or REL-002's
rejected hypothesis.

**Characterization, not yet a fix decision:** a tightly-cropped face
image (bbox-exact, no margin) can fail re-detection by the same detector
that found it reliably in the full scene with surrounding context. This
is a known category of detector behavior (scale/context-dependent
calibration), not an obviously-wrong implementation in either
`InsightFaceDocumentFaceExtractor` or `InsightFaceDetector` individually
— it is an integration property of chaining "detect and crop" into
"independently re-detect on the crop." Whether the fix is padding the
crop with a margin, having `FACE_DETECTION_REFERENCE` trust the
extractor's own successful detection instead of re-verifying, adjusting
`det_size` for the second call, or something else is not decided here.

## 6. Next boundary

This closes REL-003's own scope (localizing the discrepancy) with a
answer more specific than anticipated. A new record should be opened to
scope any fix to the tight-crop re-detection behavior before implementing
one — this record does not authorize a fix.
