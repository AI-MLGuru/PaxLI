# REL-001 — Native PaddleOCR Crash: Tracked Reliability Incident

**Status:** OPEN. This is an incident record, not an architecture decision —
nothing here is frozen, and no production code has changed as a result of
it. It exists so this finding survives the session that discovered it,
gets a fixture-substitution decision recorded honestly, and gets a
deliberate investigation scope opened later rather than being fixed
ad hoc under pressure to finish an unrelated checkpoint.

Discovered during the Synthetic/Local E2E biometric checkpoint (real
browser → real API → real Postgres/MinIO), while exercising Slice A's
production `PaddleOCREngine` against real, consenting-subject photographs
held under `tests/fixtures/biometric/` (local-only, gitignored, never
committed — see that directory's own `README.md`).

## 1. What is confirmed

- `PaddleOCREngine.extract()` — the real, production OCR capability
  (`infrastructure/document/paddle_ocr_engine.py`), wired into the real
  API via `apps/api/paxli_api/dependencies.py`, exactly as a real document
  upload would reach it — can terminate its own process with a native
  access violation (`0xC0000005` / `STATUS_ACCESS_VIOLATION`, the Windows
  equivalent of SIGSEGV). Confirmed in the real running API process, and
  independently confirmed in a fresh, isolated Python process with
  nothing else loaded (no InsightFace, no ONNX Runtime) — ruling out
  process-state/runtime interaction as a *necessary* cause.
- This is not one bad file. A structured diagnostic sweep of all 25 real
  fixture photographs (plus one derived test copy) found **8 of 26**
  images crash or intermittently except, **all within one subject's
  photo set**, and the failure rate correlates strongly with decoded
  image resolution:
  - Images at 7.99 MP (3264×2448): crash deterministically or
    near-deterministically (3-for-3 crashes observed for three of them
    across independent fresh-process attempts).
  - Images at 2.35–2.96 MP: fail intermittently as a *catchable* Python
    exception (`cv2.error: Unknown C++ exception`) roughly 1 attempt in 3,
    never as a hard crash in this sweep.
  - Every image at or below 2.96 MP that succeeded at all (5 images from
    the same subject, plus all 13 images from the second subject, 0.74–
    1.64 MP) never crashed or excepted in this sweep — though most were
    only attempted once (see §3).
- EXIF metadata, including the `Orientation` tag, is **ruled out** as the
  trigger — a byte-identical copy with EXIF stripped still crashed.
- Reducing resolution by 50% eliminated hard crashes across **all 8**
  problem images, including the three deterministic ones. Re-encoding at
  *full* resolution (JPEG quality 85, PNG, RGB JPEG quality 95) did
  **not** reliably prevent the same three from crashing.
- Full detail, the summary table, and the crash/inconsistency matrix
  live in `tests/fixtures/biometric/_diagnostics/image_diagnostics.md`
  (local-only, gitignored, referenced here by path since it contains
  filenames tied to real subject photos and is not itself committed).

## 2. What this evidence supports, and what it does not

**Supports:** decoded pixel-buffer size is *strongly associated* with
whether this crash manifests, and manifests deterministically once large
enough, inside PaddleX's text-detection postprocessing
(`cv2.findContours`, `paddlex/inference/models/text_detection/`
`processors.py:382`).

**Does not yet establish:** that pixel-buffer size is the *sole* causal
mechanism. The failure is probabilistic for part of the cluster —
identical bytes producing different outcomes (crash vs. catchable
exception vs. success) across independent fresh-process attempts at the
same resolution — which is more consistent with a memory-layout-sensitive
native defect (a bug whose manifestation depends on incidental heap/ASLR
state) than a purely deterministic, content-triggered one. Resolution is
the variable this investigation controlled and found predictive; it is
not proven to be the only one that matters. Treating "strongly
associated with 8 MP inputs" as "solved by keeping inputs under N
megapixels" would overstate what was actually shown.

## 3. Explicitly not yet tested

- Where between ~3 MP and 8 MP the risk actually ramps (only 100% and 50%
  scale were tried).
- Repeat-consistency for the images that only got one attempt in this
  sweep — a low, already-documented transient flake rate (see the
  cold-start `cv2.error` artifact noted during earlier InsightFace
  benchmarking this project) cannot be ruled out for them, only that it
  wasn't observed once.
- Whether large non-photographic images (synthetic solid-color or noise
  at 7.99 MP) reproduce the same fault, which would separate "large
  photographic content" from "large image, any content" as the trigger.

## 4. Immediate handling — fixture substitution, not silent continuation

The frozen Synthetic/Local E2E fixture mapping originally selected
`subject_a/Image_4.jpg` as the reference/document image. That selection
was already revised twice before this incident (once for exceeding the
API's 10 MB evidence-size limit, once for a genuine `NO_FACE_FOUND`
result on an AI-generated substitute), and is being revised a third time
now specifically **because of this incident** — `Image_4.jpg` itself sits
in the 7.99 MP crash cluster. This is recorded here explicitly so Run 1's
eventual result is never read as "the original frozen mapping, unmodified
end to end." The replacement candidate must independently satisfy, not
merely inherit clearance from this record: exactly one detected face,
suitable detection confidence, and a clean, previously-observed OCR
result at that same file — verified per-candidate before use, not assumed
from the resolution correlation alone.

## 5. Direction under consideration — not decided, not frozen

A layered defense is the direction discussed, not yet scoped or
authorized as an implementation:

```text
Input validation / resource limits
            |
Optional bounded image normalization
            |
Isolated OCR worker process
            |
Crash / timeout supervision
            |
UNAVAILABLE or controlled failure
```

Rationale for *why more than one layer*, recorded now so it isn't
re-litigated from scratch later: resizing/normalization may reduce
exposure and resource use, but this investigation's own evidence (§2)
already shows re-encoding/normalization alone does not reliably prevent
the deterministic crashes — it is not a sufficient reliability boundary
by itself. Process isolation is what turns "the whole API dies, every
tenant's in-flight request lost" into "one request fails, cleanly,
without new gating logic that must independently decide when it's a
"real" defect." Supervision/timeout handling is what lets that isolated
failure become an ordinary, already-understood `CapabilityUnavailableError`
-shaped outcome rather than a bespoke new failure path.

None of this is authorized for implementation by this record. A future
slice must open its own discovery/reconciliation pass — covering worker
process lifecycle, IPC shape, timeout values, and how `UNAVAILABLE`
propagates back through `DocumentProcessor`'s existing
`CapabilityUnavailableError` handling — before any of it is built.

## 6. Next boundary

No implementation follows from this record directly. The Synthetic/Local
E2E checkpoint continues with a validated fixture substitution (§4). A
dedicated OCR reliability investigation is future work, to be opened and
scoped deliberately, not assumed from this incident record alone.
