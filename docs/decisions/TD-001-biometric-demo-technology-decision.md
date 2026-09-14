# TD-001 — PaxLI Biometric Demo Technology Decision

**Status:** FROZEN.

**Naming note, flagged rather than silently assumed:** this is a new
series (`TD-`, Technology Decision), distinct from `DP-`/`BP-`. It
doesn't belong under `BP-` because it isn't an architecture decision —
BP-001/BP-001.5's frozen architecture (`FaceDetector`,
`FaceQualityAssessor`, `FaceEmbedder`, `FaceMatcher`, per BP-001.5
Decision 18-22) is completely untouched by anything here. This document
only picks the concrete library/model/runtime that will sit *behind*
`FaceEmbedder`/`FaceDetector` for the technical demo — an
implementation choice, not an architectural one.

**Scope:** the technical-demo face stack only. Does not select, imply,
or constrain PaxLI's eventual commercial production face model —
that's explicitly a separate, later, unmade decision (see below).

---

## Decision

```text
Face framework:        InsightFace (MIT-licensed code)
Demo model:             buffalo_l
Model license status:   Research/demo only — NOT approved for
                         commercial production (InsightFace's own
                         pretrained-model license; separate commercial
                         licensing would be required to ship it)
Runtime:                ONNX Runtime, CPUExecutionProvider
Face pipeline modules:  detection + recognition only
Excluded modules:       gender/age, 3D landmarks (2d106det/1k3d68) —
                         not needed for 1:1 verification, and
                         materially cheaper to exclude (see Memory below)
Embedding:               512-dimensional, float32, L2-normalized
                         (confirmed via direct inspection, not assumed)
Similarity:              cosine
Threshold calibration:  NOT decided here — a later evidence/research
                         task, per BP-001.5's own explicit boundary
                         (this benchmark observed similarity
                         distributions; it did not, and must not, be
                         read as setting a verification threshold)
Threading:              use InsightFace/ONNX Runtime defaults —
                         explicit thread tuning is explicitly REJECTED
                         below, not merely undecided
```

## Why InsightFace + `buffalo_l`, briefly

Evaluated against `face_recognition`/dlib, MediaPipe, DeepFace, and
OpenCV (none chosen as the recognition foundation — see the
conversation record for the full reasoning): InsightFace's code is
MIT-licensed with no commercial restriction, ONNX Runtime is
MIT-licensed with no commercial restriction, and `buffalo_l` (RetinaFace
detection + `w600k_r50` ArcFace recognition) is InsightFace's
actively-maintained default pack — the right choice for engineering
validation even though its own weights carry a separate,
non-commercial-only license.

## Licensing boundary (carried forward from prior research, restated here as the operative constraint)

```text
InsightFace buffalo_l
        |
        +-- Technical demo / engineering research   -> APPROVED
        |
        `-- Commercial PaxLI production               -> NOT FROZEN
                |
                +-- commercial InsightFace license, or
                `-- alternative / independently licensed weights
```

PaddleOCR has no equivalent restriction — library and pretrained
PP-OCR models are both Apache 2.0, clean for both demo and commercial
use; no further licensing decision needed there.

## Benchmark evidence (this dev machine, Windows, 12 logical CPUs, CPU-only)

All numbers below are **engineering validation data**, not a production
capacity commitment — see the explicit non-conclusions section.

**Correctness — clean pass:**

| Check | Result |
|---|---|
| Embedding shape | 512-D, `float32`, L2-normalized (norm=1.0000) |
| Different-identity separation | 0.0447 cosine similarity (two distinct public-domain portraits) |
| Same-identity stability under blur/low-res/lighting/crop | 0.91-0.97 |
| Multi-face cardinality | Correctly reports 2 faces in a two-face composite |
| No-face input (random noise, flat gray) | Returns `[]`, no exception, <1s |

**Cold start (model load), weights already cached on disk:**

| Configuration | Time |
|---|---|
| Default modules (all 5) | 6.3s |
| Restricted modules (detection+recognition) | 11.3s |
| Restricted modules + explicit 12-thread `sess_options` | 18.4s |

The originally-reported **124.4s** cold start was a one-time artifact
of the fresh model download (most likely Windows Defender scanning
newly-written files on first access), not a representative number —
corrected here explicitly rather than left standing.

**Memory (real process RSS via `psutil`, not `tracemalloc`):**

| Checkpoint | RSS |
|---|---|
| Process start | 58MB |
| After `import insightface` | 100MB |
| After default-modules load | 376MB |
| After default-modules inference | ~530-600MB |
| After restricted-modules load | 231MB |
| After restricted-modules inference | 319MB |

Restricting to detection+recognition roughly halves the footprint —
the one unambiguous, directly actionable finding from this pass.

**Per-image inference — the important, non-obvious finding:**

| Configuration | Result |
|---|---|
| Default modules, default threading | **1.4-1.9s** (stable across two independent runs) |
| Restricted modules, default threading | mean=8.4s, min=4.8s (n=5; no max was captured in this run — high variance, not a min-max range) |
| Restricted modules + explicit `intra_op_num_threads=12` | 9.2s mean, stdev 0.69s (stable, and worse) |
| Raw ONNX Runtime, recognition model *in isolation*, 1 thread | 4,967ms mean / 416ms min (huge spread) |
| Raw ONNX Runtime, recognition model *in isolation*, 12 threads | 294ms mean |

The isolated single-op test suggested "more threads help enormously."
Applying that same setting to the real multi-session `FaceAnalysis`
pipeline made it consistently **worse**, not better — most likely
thread-pool oversubscription across the detector's and recognizer's
independently-threaded ONNX sessions competing for the same 12 cores.
**Every hand-tuned configuration tried was worse than the untouched
default.** The tuning sweep was deliberately stopped at this point
rather than continued indefinitely — the honest baseline to record is
the *default*, untuned configuration.

## Explicit decisions made here

1. **Face pipeline uses `allowed_modules=["detection", "recognition"]`**
   — gender/age and landmark modules are excluded. This is a demo
   *implementation* configuration choice, not a new architectural
   decision; it fits entirely inside `FaceDetector`/`FaceEmbedder`'s
   already-frozen boundary (BP-001.5 Decision 18/§7).
2. **Do not explicitly configure `intra_op_num_threads`.** Use
   ONNX Runtime's own defaults. This is a rejection of a specific
   tuning attempt, backed by measured evidence it makes things worse
   on this machine — not merely "we didn't get to it."
3. **Observed demo baseline: ~1.4-1.9s/image**, current Windows dev
   environment, default configuration, CPU-only, single process,
   single image at a time.

## Explicit non-conclusions — what this benchmark does NOT establish

- **NOT a throughput ceiling.** This measured one process handling one
  image serially. It says nothing about multiple workers, multiple
  containers, request concurrency, batching, or queue-based processing
  — all real levers for a KYC API where throughput matters more than
  single-image latency.
- **NOT a deployment-target number.** One Windows development machine,
  not Linux, not the actual production CPU generation, not a
  container.
- **NOT a verification threshold.** Observed similarity distributions
  (0.04 different-identity, 0.91-0.97 same-identity-degraded) are
  evidence for later threshold-calibration work, per BP-001.5's own
  boundary — not a frozen threshold.
- **NOT a resolved performance question.** The thread-oversubscription
  hypothesis for why explicit tuning hurt is a plausible explanation,
  not confirmed. Real perf engineering (a cleaner benchmark
  environment, ONNX Runtime's shared-environment threading APIs) is
  explicitly deferred, not solved here.

## Production model decision — NOT YET SELECTED

```text
FaceEmbedder
     |
     +-- Demo implementation (this decision)
     |       InsightFace buffalo_l, ONNX Runtime CPU
     |
     `-- Production implementation (NOT decided)
             requires, at minimum:
               - accuracy evaluation
               - latency/throughput evaluation on real infra
               - licensing resolution (commercial InsightFace
                 license, or independently licensed/sourced weights)
               - deployment review
```

`buffalo_l` appears only inside the demo's infrastructure adapter,
never in `core/`'s domain/application layers — the same
capability-boundary discipline already frozen for document processing
(`core/document/capabilities.py`) and for biometrics generally
(BP-001.5 Decision 18, `FaceDetector`/`FaceEmbedder` as ports). Swapping
the demo model for a commercially-licensed production one later means
writing a new adapter behind the same port, not touching `FaceMatcher`,
`ReferenceIdentity`, lineage, or the Decision Engine.

---

No production code has been written. This decision authorizes the
demo implementation plan to proceed with a named, justified technology
choice — it does not itself constitute that plan.
