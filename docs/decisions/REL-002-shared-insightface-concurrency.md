# REL-002 — Shared InsightFace Instance: Suspected Concurrency Reliability Issue

**Status:** CLOSED — hypothesis rejected by direct experiment (§7). The
underlying symptom (§1) is not resolved; only this specific explanation
for it is. Follow-on investigation continues under REL-003.

**Status (original):** OPEN. This is an incident record, not an architecture decision —
nothing here is frozen, and no production code has changed as a result of
it. Distinct from [REL-001](REL-001-paddleocr-native-crash-incident.md)
(native PaddleOCR crash): different component, different failure shape
(wrong result, not a process-terminating crash), discovered independently
while investigating a different symptom.

Discovered while resuming the Synthetic/Local E2E biometric checkpoint
after REL-001's fixture substitution, using `subject_a/Image_1.jpg`
(reference/document) and `subject_a/Image_7.jpg` (selfie/probe) — the
fixture pair selected specifically because it cleared REL-001's OCR crash
cluster and passed a serial, in-process InsightFace check.

## 1. What is confirmed

- Real session `dcf00a1b-58ef-4824-9202-f91413e88d32` reached `COMPLETED`
  with outcome `INCONCLUSIVE`. Persisted evidence:
  `FACE_DETECTION_PROBE=PASS`, `FACE_EMBEDDING_PROBE=PASS`,
  `FACE_QUALITY_PROBE=PASS` (probe side, `Image_7.jpg`, all clean) but
  `FACE_DETECTION_REFERENCE=INCONCLUSIVE` / `DETECTION_NO_FACE` (reference
  side, `Image_1.jpg`).
- This directly contradicts the diagnostic sweep's own finding for the
  same file: `face_diagnostics()` in
  `tests/fixtures/biometric/_diagnostics/run_diagnostics.py` recorded
  `face_count=1`, `det_score=0.8659`, `bbox_w=550.3`, `bbox_h=776.2` for
  `subject_a/Image_1.jpg`.
- The following causes were checked directly and ruled out:
  - **Upload/storage corruption.** The `evidence.checksum` column
    (`sha256(content).hexdigest()`, computed server-side at upload —
    `apps/api/paxli_api/routers/evidence.py:93`) for the DOCUMENT capture
    in this session is `b0e9c98f...`, an exact match to a local SHA-256 of
    `subject_a/Image_1.jpg`. The uploaded bytes are unmodified end to end.
  - **Decode-path difference.** Production decodes via
    `cv2.imdecode(np.frombuffer(image, ...), cv2.IMREAD_COLOR)`
    (`infrastructure/face/document_face_extractor.py:64`); the diagnostic
    script used `cv2.imread(path)`. Direct comparison on the identical
    bytes: `np.array_equal(imread_result, imdecode_result) == True`.
    Decode is not the source of the difference.
  - **Model configuration difference.** Both the diagnostic script and
    `InsightFaceDocumentFaceExtractor.__init__` construct
    `FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"],
    allowed_modules=["detection"])` and call
    `prepare(ctx_id=-1, det_size=(640, 640))`. No parameter differs.
  - **Model nondeterminism in isolation.** Three fresh-process repeats of
    the exact production config against the exact same file all found
    1 face at `det_score=0.8659`. Deterministic when run standalone.
- The real structural difference found: `apps/api/paxli_api/dependencies.py`
  (`_get_shared_detection_face_analysis`, lines 95–118) deliberately shares
  **one** `FaceAnalysis` instance across three consumers —
  `InsightFaceDetector` (probe detection), `InsightFaceQualityAssessor`
  (probe quality), and `InsightFaceDocumentFaceExtractor`
  (reference/document detection) — each invoked via
  `asyncio.to_thread(self._app.get, ...)`. A single verification
  submission processes the document and selfie evidence within the same
  request, so this shared instance can receive calls from more than one
  thread pool thread at close to the same time. The diagnostic script
  never replicated this: every one of its calls was a dedicated instance
  handling exactly one image, serially, in its own process.

## 2. What this evidence supports, and what it does not

**Supports:** every simpler explanation (corrupted bytes, decode-path
difference, model config difference, plain model nondeterminism) has been
directly checked and ruled out. The one remaining structural difference
between "works every time" and "failed once in the real server" is the
shared-instance-under-concurrent-invocation shape.

**Does not yet establish:** that concurrent access to the shared
`FaceAnalysis`/ONNX Runtime session is the actual mechanism, or that it is
reliably reproducible outside the one observed failure. No deliberate
concurrent-call reproduction has been run yet (see §3 / next steps). This
record exists specifically so that reproduction attempt has a fixed,
honest starting point, not a foregone conclusion.

## 3. Explicitly not yet tested (at record-creation time)

- Whether a second submission of the identical fixture pair reproduces
  the same `DETECTION_NO_FACE` result (intermittent vs. one-off).
- Whether deliberately driving concurrent `.get()` calls into the shared
  instance (mirroring the real request's document+selfie timing)
  reproduces a wrong or missing detection outside the live server.
- Whether serializing access to the shared instance (a lock around
  `.get()`) prevents the symptom under the same concurrent scheduling.

## 4. Immediate handling

No code changes yet. `subject_a/Image_1.jpg` is not disqualified as a
fixture by this finding — its own detectability is independently
confirmed (§1) — but Run 1 of the frozen E2E checkpoint has not yet
produced a clean `FACE_DETECTION_REFERENCE=PASS` result, so "successful
document/reference extraction" (one of the four independent checks
required for any replacement fixture, per this checkpoint's own frozen
criteria) is not yet satisfied for this file in the real pipeline. A
controlled retry and a focused concurrency experiment are the immediate
next steps, run and reported before any production code changes.

## 5. Direction under consideration — not decided, not frozen

If concurrency is confirmed as the mechanism, candidate directions
(none authorized for implementation by this record):

- A lock around the shared instance's `.get()` call.
- Dedicated `FaceAnalysis` instances per capability (reverses the
  memory/latency trade-off `_get_shared_detection_face_analysis`'s own
  docstring already recorded as the reason for sharing in the first
  place — BD-001.10 I-1 — so reversing it is not free).
- A dedicated biometric inference worker with controlled concurrency.
- Process isolation, if the underlying defect turns out to be a native
  runtime issue rather than a pure Python-level race.

Evaluating between these requires first confirming the failure mode, per
§3 — the same discipline already applied to REL-001 §5.

## 6. Next boundary (as originally written)

A controlled retry of Run 1 (same fixture pair, new session, full evidence
captured) and a focused concurrency experiment (dedicated-serial vs.
shared-serial vs. shared-concurrent, at minimum) follow directly from this
record. No fix is authorized until those report back.

## 7. Controlled retry and concurrency experiment — results

**Controlled retry.** A second, independent submission of the identical
fixture pair (new session `62edf65e-6169-41b7-8798-d874af8fa85d`, same
already-running server process as the original `dcf00a1b-...` session)
reproduced the exact same result: `FACE_DETECTION_REFERENCE=INCONCLUSIVE`
/ `DETECTION_NO_FACE`, with `FACE_DETECTION_PROBE`/`FACE_QUALITY_PROBE`
clean on both attempts, `FACE_QUALITY_PROBE` scoring the identical value
(`0.5639218668999181`) both times. Failure is 2-for-2 in the live server,
against 3-for-3 success in every isolated repro — a clean split, not an
intermittent rate, which argued against a rare race before the
concurrency experiment below was run.

**Concurrency experiment.** Three modes were run against the identical
fixture pair (`subject_a/Image_1.jpg` reference, `subject_a/Image_7.jpg`
probe), each in its own fresh subprocess for crash-safety:

| Mode | Setup | Result |
|---|---|---|
| A | Dedicated `FaceAnalysis` instance per image, serial | 1/1 face found, `det_score=0.8659` |
| B | One shared instance, both images, serial | 1/1 face found, `det_score=0.8659` |
| C | One shared instance, both images, concurrent (5 rounds × 2 simultaneous calls via `threading.Thread`) | 15/15 face found, `det_score=0.8659` every round |

**Conclusion: no reproduction under any tested condition.** Deliberately
sharing the instance and deliberately driving concurrent calls into it —
mirroring the real request's document+selfie timing — did not perturb
the result once, across 17 total calls. The shared-instance-concurrency
hypothesis, as tested here, is rejected by this evidence.

**Scope of this rejection — read narrowly.** This closes the specific
hypothesis and the specific configuration tested: two threads, one
process, calling `.get()` on the same warm `buffalo_l` detection-only
instance for exactly these two images. It does not establish that no
concurrency-related issue exists anywhere in the shared-instance design,
under different thread counts, different image pairs, sustained load, or
interaction with the separate embedder instance — those configurations
were not tested and no claim is made about them.

**Residual uncertainty.** The exact live server call path at the moment
of the original failures remains unobserved — every check so far has
been either indirect (checksums, DB state) or a reconstruction run
outside the live process. What the live server actually passed to
`self._app.get(...)` at that moment — array shape, dtype, contiguity,
det_size, which instance — has not been directly captured. That gap is
what [REL-003](REL-003-reference-extraction-instrumentation.md) exists
to close.
