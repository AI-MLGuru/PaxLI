"""BD-001 Slices B, C, and D: the first real (non-stand-in)
`core.face.capabilities` implementations. TD-001's frozen technology
choice (InsightFace `buffalo_l`, ONNX Runtime CPU) applied to detection,
quality assessment, and (Slice D) recognition/embedding.

Nothing about InsightFace's own `Face` object (bbox, det_score, kps,
embedding) is ever visible past this module -- `InsightFaceDetector`
reports only `detected`/`face_count`, `InsightFaceQualityAssessor`
reports only a bounded `quality_score`, `InsightFaceEmbedder` reports
only a validated `embedding`/`embedding_dimensions`/`model_reference`,
exactly their frozen `FaceDetection`/`FaceQuality`/`FaceEmbedding`
contracts, the same "don't let the vendor SDK's shape leak into core/"
discipline `PaddleOCREngine` already established for OCR.

The three adapters are independent at the capability-port level (none
imports or references another, per BD-001 Slices C/D's own frozen
reconciliation) even though they live in one file and may each run
their own internal InsightFace detection -- file co-location is not
port-level coupling.
"""

import asyncio

import cv2
import numpy as np
import onnxruntime
from insightface.app import FaceAnalysis

from core.evidence_result.models import ModelReference
from core.face.capabilities import (
    CapabilityUnavailableError,
    FaceDetector,
    FaceEmbedder,
    FaceQualityAssessor,
)
from core.face.reason_codes import FaceReasonCode
from core.face.types import (
    FaceDetection,
    FaceDetectionOutcome,
    FaceEmbedding,
    FaceEmbeddingOutcome,
    FaceQuality,
    FaceQualityOutcome,
)


class InsightFaceDetector(FaceDetector):
    """Wraps a single, long-lived `FaceAnalysis` instance -- model load
    is expensive (TD-001 measured 6-18s depending on configuration) and
    MUST NOT happen per request, the same discipline
    `infrastructure.document.paddle_ocr_engine.PaddleOCREngine` already
    established.

    `allowed_modules=["detection"]` only -- Slice B needs no recognition
    model (that's Slice D's own adapter, not yet built). Whether a
    future embedder shares this exact `FaceAnalysis` instance, adds
    "recognition" to this same instance, or constructs its own is
    explicitly NOT decided here (BD-001 Slice B: "internal session
    topology... subject to measurement," per TD-001's own
    counter-intuitive restricted-module benchmark result) -- this
    adapter is deliberately minimal for what Slice B alone needs.
    """

    def __init__(
        self,
        *,
        det_size: tuple[int, int] = (640, 640),
        app: FaceAnalysis | None = None,
    ) -> None:
        """`app`, if supplied, is used directly instead of constructing a
        real `FaceAnalysis` pipeline -- the seam unit tests use to
        exercise `detect()`'s own decode/translation logic without
        paying a real model's multi-second load cost, the same pattern
        `PaddleOCREngine`'s `ocr=` parameter already established.
        Production call sites never pass it."""
        if app is not None:
            self._app = app
        else:
            self._app = FaceAnalysis(
                name="buffalo_l",
                providers=["CPUExecutionProvider"],
                allowed_modules=["detection"],
            )
            self._app.prepare(ctx_id=-1, det_size=det_size)

    async def detect(self, image: bytes) -> FaceDetection:
        image_array = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image_array is None:
            # Same reasoning PaddleOCREngine already documents in full:
            # core/evidence/media_validation.py verifies only the file
            # signature, not full decodability, so a corrupted-but-
            # correctly-signed upload reaching this adapter as real
            # bytes is reachable in production, not hypothetical.
            # BD-001 Slice B (this reconciliation pass) corrects an
            # earlier draft that proposed CapabilityUnavailableError
            # here -- undecodable bytes are FaceDetectionOutcome's own
            # UNREADABLE outcome, not a capability/infrastructure
            # failure.
            return FaceDetection(
                outcome=FaceDetectionOutcome.UNREADABLE, detected=None, face_count=None
            )
        faces = await asyncio.to_thread(self._app.get, image_array)
        return FaceDetection(
            outcome=FaceDetectionOutcome.VALID,
            detected=len(faces) > 0,
            face_count=len(faces),
        )


# --- Quality signal normalization -----------------------------------------
#
# Every constant below is an explicit, named DEMO CALIBRATION CONSTANT, not
# a scientifically derived threshold -- `quality_score` is a bounded
# heuristic score, never a calibrated probability of image quality. Each
# signal is normalized independently, on its own documented reasoning,
# before being combined -- never a bare "divide by a number and clip" with
# no stated rationale.

# Laplacian variance has no natural upper bound and scales with image
# content/resolution -- there is no universal "sharp" value. This constant
# is a commonly-cited ad-hoc threshold from OpenCV blur-detection
# tutorials/community practice (variance below ~100 is conventionally
# "blurry" for a modest-resolution crop), chosen as a starting point for a
# demo, not derived from this project's own data. Revisit with real
# calibration data before any production use -- explicitly flagged, not
# silently assumed to be correct.
_BLUR_VARIANCE_CALIBRATION = 100.0

# Mid-range brightness (128 of 0-255) is treated as ideal; deviation in
# either direction (too dark or too bright/overexposed) reduces the score
# linearly, symmetric around the midpoint. Also a demo heuristic, not a
# photometric standard.
_IDEAL_BRIGHTNESS = 128.0


def _normalize_blur(face_region_gray: np.ndarray) -> float:
    """Higher Laplacian variance = sharper. Bounded to [0.0, 1.0] via the
    named calibration constant above -- never left as a raw, unbounded
    variance value."""
    variance = float(cv2.Laplacian(face_region_gray, cv2.CV_64F).var())
    return min(variance / _BLUR_VARIANCE_CALIBRATION, 1.0)


def _normalize_brightness(face_region_gray: np.ndarray) -> float:
    """1.0 at the ideal midpoint, decreasing linearly toward 0.0 at either
    extreme (fully black or fully white). Explicitly clamped to [0.0, 1.0]
    at both ends -- mathematically redundant given a uint8 input's
    guaranteed [0, 255] range, but made explicit rather than relying on
    the reader to trust that unstated guarantee, the same defensive
    posture applied to `det_score` below."""
    mean_intensity = float(np.mean(face_region_gray))
    return max(0.0, min(1.0, 1.0 - abs(mean_intensity - _IDEAL_BRIGHTNESS) / _IDEAL_BRIGHTNESS))


class InsightFaceQualityAssessor(FaceQualityAssessor):
    """Deliberately independent of `InsightFaceDetector` at the capability
    level (core.face.capabilities.FaceQualityAssessor's own contract) --
    runs its own detection internally to establish cardinality and obtain
    the bbox/det_score it needs, exactly like `InsightFaceDetector` does.
    Any future sharing of the underlying `FaceAnalysis` instance between
    the two adapters is an infrastructure-only optimization, wired later
    (BD-001 Slice G), never a port-level coupling -- this class doesn't
    import or reference `InsightFaceDetector` at all."""

    def __init__(
        self,
        *,
        det_size: tuple[int, int] = (640, 640),
        app: FaceAnalysis | None = None,
    ) -> None:
        """`app`, if supplied, is used directly -- the same injection seam
        `InsightFaceDetector`/`PaddleOCREngine` already establish, for
        hermetic unit tests and for a future DI-wiring decision to share
        one `FaceAnalysis` instance across both adapters."""
        if app is not None:
            self._app = app
        else:
            self._app = FaceAnalysis(
                name="buffalo_l",
                providers=["CPUExecutionProvider"],
                allowed_modules=["detection"],
            )
            self._app.prepare(ctx_id=-1, det_size=det_size)

    async def assess(self, image: bytes) -> FaceQuality:
        image_array = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image_array is None:
            return FaceQuality(outcome=FaceQualityOutcome.UNREADABLE, quality_score=None)

        faces = await asyncio.to_thread(self._app.get, image_array)
        if len(faces) == 0:
            return FaceQuality(outcome=FaceQualityOutcome.NO_FACE, quality_score=None)
        if len(faces) > 1:
            # No selection, ever -- BP Decision B-2's own boundary, applied
            # identically here rather than picking "the primary face."
            return FaceQuality(outcome=FaceQualityOutcome.AMBIGUOUS, quality_score=None)

        face = faces[0]
        height, width = image_array.shape[:2]
        x1, y1, x2, y2 = face.bbox
        # Clip to image bounds -- detector bboxes can extend slightly past
        # the frame edge in practice; cropping with an out-of-bounds index
        # would silently misbehave rather than raise.
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(width, int(x2)), min(height, int(y2))
        if x2 <= x1 or y2 <= y1:
            # A bbox that clips to zero or negative width/height -- e.g.
            # one that landed entirely outside the frame. Not a normal
            # "zero faces"/"multiple faces" outcome (a face WAS reported);
            # not an input-decodability problem either (the image itself
            # decoded fine) -- this is the detector's own output being
            # unusable for this computation, a genuine capability-level
            # anomaly. Raising rather than silently proceeding:
            # image_array[y1:y2, x1:x2] on a degenerate range produces an
            # EMPTY ndarray, not an error -- np.mean/cv2.Laplacian on that
            # would silently produce NaN, corrupting quality_score past
            # its frozen [0.0, 1.0] contract. Never let that happen quietly.
            raise CapabilityUnavailableError(FaceReasonCode.QUALITY_DEGENERATE_CROP.value)
        face_region = cv2.cvtColor(image_array[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)

        blur_score = _normalize_blur(face_region)
        brightness_score = _normalize_brightness(face_region)
        # Defensively clamped even though InsightFace currently always
        # reports det_score in [0, 1] -- cheap protection at the vendor
        # boundary against a future model version or numerical edge case
        # silently breaking quality_score's own frozen output contract.
        # det_score is a detector CONFIDENCE-like signal, one input among
        # three -- never itself the "quality heuristic"; that term names
        # only the combined quality_score below.
        det_score = max(0.0, min(1.0, float(face.det_score)))
        # Unweighted mean of three independently-normalized [0.0, 1.0]
        # signals -- an explicit, simple combination choice, not a
        # calibrated model. Equal weighting is itself a demo-only
        # assumption, not evidence that these three signals matter equally
        # to real face-match accuracy. Bounded to [0.0, 1.0] by
        # construction: the mean of three values each already clamped to
        # that range cannot fall outside it.
        quality_score = (blur_score + brightness_score + det_score) / 3.0

        return FaceQuality(outcome=FaceQualityOutcome.VALID, quality_score=quality_score)


# --- Embedding representation validation (D-4) ------------------------
#
# TD-001's frozen contract: 512-dimensional, L2-normalized. The adapter is
# responsible for enforcing this at the vendor boundary -- validated, never
# silently repaired (BD-001 Slice D's own explicit instruction: no
# re-normalization). The norm tolerance is an explicit, named constant,
# stated and tested at its boundary rather than an unstated magic number.

_EXPECTED_EMBEDDING_DIMENSIONS = 512

# Genuine float32 L2-normalization noise over a 512-dimension vector is
# many orders of magnitude smaller than this -- 1e-3 is generous enough to
# never false-positive on ordinary numerical rounding, while still easily
# catching a genuinely wrong representation (the raw, non-normalized
# `.embedding` attribute has norm ~19, three orders of magnitude outside
# this tolerance -- confirmed via this project's own TD-001 benchmark).
_NORM_TOLERANCE = 1e-3


class InsightFaceEmbedder(FaceEmbedder):
    """Wraps a single, long-lived `FaceAnalysis` instance with
    `allowed_modules=["detection", "recognition"]` -- unlike
    `InsightFaceDetector`/`InsightFaceQualityAssessor`, this adapter needs
    the recognition module. Does no manual cropping/alignment of its own
    (BD-001 Slice D, D-2): InsightFace's own `.get()` call performs
    detection, landmarking, alignment, and recognition together, and
    `face.normed_embedding` is that fully-computed result -- there is no
    project-owned bbox-slicing step here the way `InsightFaceQualityAssessor`
    has, so that adapter's empty-crop failure mode structurally cannot
    occur in this one."""

    def __init__(
        self,
        *,
        det_size: tuple[int, int] = (640, 640),
        app: FaceAnalysis | None = None,
        model_id: str = "insightface/buffalo_l/w600k_r50",
        model_version: str = "buffalo_l",
    ) -> None:
        """`app`, if supplied, is used directly -- the same injection seam
        every adapter in this module establishes, for hermetic unit tests
        and a future DI-wiring decision about instance sharing."""
        if app is not None:
            self._app = app
        else:
            self._app = FaceAnalysis(
                name="buffalo_l",
                providers=["CPUExecutionProvider"],
                allowed_modules=["detection", "recognition"],
            )
            self._app.prepare(ctx_id=-1, det_size=det_size)
        # Captured once at construction, not per-call -- model identity is
        # a property of this adapter instance, not of any individual
        # image. BD-001's own frozen spec: model_version is buffalo_l's
        # own coarse pack version ("exact per-file hash/version pinning is
        # implementation detail, not frozen here"); runtime_version is
        # read live from onnxruntime itself, never hardcoded.
        self._model_reference = ModelReference(
            model_id=model_id,
            model_version=model_version,
            runtime="onnxruntime",
            runtime_version=onnxruntime.__version__,
        )

    async def embed(self, image: bytes) -> FaceEmbedding:
        image_array = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image_array is None:
            return FaceEmbedding(
                outcome=FaceEmbeddingOutcome.UNREADABLE,
                embedding=None,
                embedding_dimensions=None,
                model_reference=None,
            )

        faces = await asyncio.to_thread(self._app.get, image_array)
        if len(faces) == 0:
            return FaceEmbedding(
                outcome=FaceEmbeddingOutcome.NO_FACE,
                embedding=None,
                embedding_dimensions=None,
                model_reference=None,
            )
        if len(faces) > 1:
            # No selection, ever -- BP Decision B-2's own boundary,
            # applied identically here.
            return FaceEmbedding(
                outcome=FaceEmbeddingOutcome.AMBIGUOUS,
                embedding=None,
                embedding_dimensions=None,
                model_reference=None,
            )

        # D-3: normed_embedding, never the raw embedding attribute.
        embedding = faces[0].normed_embedding

        # D-4: validate the vendor's own output before trusting it --
        # dimensionality, finiteness, then norm, in that order (a
        # dimension check must precede a norm check that assumes a
        # 512-length vector).
        if embedding.shape[0] != _EXPECTED_EMBEDDING_DIMENSIONS:
            raise CapabilityUnavailableError(FaceReasonCode.EMBEDDING_INVALID_REPRESENTATION.value)
        if not np.all(np.isfinite(embedding)):
            raise CapabilityUnavailableError(FaceReasonCode.EMBEDDING_INVALID_REPRESENTATION.value)
        norm = float(np.linalg.norm(embedding))
        if not np.isfinite(norm) or norm <= 0.0:
            raise CapabilityUnavailableError(FaceReasonCode.EMBEDDING_INVALID_REPRESENTATION.value)
        if abs(norm - 1.0) > _NORM_TOLERANCE:
            # Never re-normalize to make this pass -- a vendor-claimed
            # "normalized" embedding that isn't actually normalized is a
            # genuine anomaly to surface, not silently correct.
            raise CapabilityUnavailableError(FaceReasonCode.EMBEDDING_INVALID_REPRESENTATION.value)

        # VALID only once the representation AND its model reference are
        # both established -- constructed in one return, never partially.
        return FaceEmbedding(
            outcome=FaceEmbeddingOutcome.VALID,
            embedding=tuple(float(x) for x in embedding),
            embedding_dimensions=int(embedding.shape[0]),
            model_reference=self._model_reference,
        )
