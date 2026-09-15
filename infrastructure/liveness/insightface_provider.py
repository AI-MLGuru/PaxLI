"""BD-001 Slice F: the first real (non-stand-in) `core.liveness.provider`
implementation. TD-001's frozen technology choice (InsightFace
`buffalo_l`, ONNX Runtime CPU) applied to landmark detection only --
`allowed_modules=["detection"]`, the same minimal footprint
`InsightFaceDetector`/`InsightFaceQualityAssessor` use, since landmarks
(`kps`) come from the detection module itself, no recognition needed.

Nothing about InsightFace's own `Face` object (bbox, det_score, kps,
embedding) is ever visible past this module -- this adapter reports
only the frozen `LivenessEvidence` contract, the same "don't let the
vendor SDK's shape leak into core/" discipline every other adapter in
this project already establishes.

Explicitly a Temporal Liveness Demo, not production PAD -- see
core/liveness/provider.py's own module docstring for the full
limitation statement (defeated by video replay, prone to hand-tremor
false positives).
"""

import asyncio

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from core.liveness.exceptions import CapabilityUnavailableError
from core.liveness.provider import LivenessEvidence, LivenessOutcome, LivenessProvider
from core.liveness.reason_codes import LivenessReasonCode

# Interocular-distance normalization makes the displacement measure
# scale-invariant (a face closer to the camera moves more raw pixels for
# the same real motion) -- a real refinement over a raw-pixel threshold,
# not merely a stylistic choice. The calibration constant below is still
# an explicit, named DEMO value, not scientifically derived: 0.05 means
# mean inter-frame landmark displacement equal to 5% of interocular
# distance is treated as "fully live" movement. Revisit with real
# calibration data before any production use.
_DISPLACEMENT_CALIBRATION = 0.05


class InsightFaceLivenessProvider(LivenessProvider):
    """Wraps a single, long-lived `FaceAnalysis` instance -- model load is
    expensive and MUST NOT happen per request, the same discipline every
    adapter in this project already establishes."""

    def __init__(
        self,
        *,
        det_size: tuple[int, int] = (640, 640),
        app: FaceAnalysis | None = None,
    ) -> None:
        """`app`, if supplied, is used directly -- the same injection seam
        every InsightFace adapter in this project establishes, for
        hermetic unit tests and a future DI-wiring decision about
        instance sharing."""
        if app is not None:
            self._app = app
        else:
            self._app = FaceAnalysis(
                name="buffalo_l",
                providers=["CPUExecutionProvider"],
                allowed_modules=["detection"],
            )
            self._app.prepare(ctx_id=-1, det_size=det_size)

    async def assess(self, frames: list[bytes]) -> LivenessEvidence:
        # Sequence-level precondition, checked first, before any frame's
        # bytes are touched -- there is no pair of frames to compute a
        # displacement from with fewer than 2.
        if len(frames) < 2:
            return LivenessEvidence(
                outcome=LivenessOutcome.INSUFFICIENT_FRAMES,
                live_score=None,
                attack_score=None,
            )

        # Per-frame scan, in submission order, stopping at the first
        # frame with any problem -- no global severity ranking between
        # UNREADABLE/NO_FACE/AMBIGUOUS, per this project's own
        # reconciliation (core/liveness/provider.py's own docstring).
        landmarks: list[np.ndarray] = []
        for frame in frames:
            image_array = cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image_array is None:
                return LivenessEvidence(
                    outcome=LivenessOutcome.UNREADABLE, live_score=None, attack_score=None
                )
            faces = await asyncio.to_thread(self._app.get, image_array)
            if len(faces) == 0:
                return LivenessEvidence(
                    outcome=LivenessOutcome.NO_FACE, live_score=None, attack_score=None
                )
            if len(faces) > 1:
                return LivenessEvidence(
                    outcome=LivenessOutcome.AMBIGUOUS, live_score=None, attack_score=None
                )
            landmarks.append(faces[0].kps)

        live_score = self._compute_live_score(landmarks)
        return LivenessEvidence(
            outcome=LivenessOutcome.VALID,
            live_score=live_score,
            attack_score=None,  # intentional -- see core/liveness/provider.py's own docstring
            signals=("landmark_displacement",),
        )

    def _compute_live_score(self, landmarks: list[np.ndarray]) -> float:
        normalized_displacements = []
        # Deliberately strict=False: landmarks[1:] is intentionally one
        # element shorter than landmarks -- this pairs each frame with
        # its successor (N frames -> N-1 consecutive pairs), not two
        # same-length sequences that should match exactly.
        for kps_a, kps_b in zip(landmarks, landmarks[1:], strict=False):
            raw_displacement = float(np.mean(np.linalg.norm(kps_a - kps_b, axis=1)))
            if not np.isfinite(raw_displacement):
                # A NaN/inf landmark coordinate from the vendor SDK
                # propagates here even though every frame individually
                # passed its own decode/cardinality checks -- the
                # provider's own inability to safely compute the
                # heuristic, never a claim that the subject failed
                # liveness. Raised, never silently carried into
                # live_score as a corrupted value.
                raise CapabilityUnavailableError(LivenessReasonCode.DEGENERATE_LANDMARKS.value)
            interocular_a = float(np.linalg.norm(kps_a[0] - kps_a[1]))
            interocular_b = float(np.linalg.norm(kps_b[0] - kps_b[1]))
            interocular_avg = (interocular_a + interocular_b) / 2.0
            if not np.isfinite(interocular_avg) or interocular_avg <= 0.0:
                # Every frame individually passed its own decode/
                # cardinality checks -- this is the provider's own
                # inability to safely compute the heuristic (dividing by
                # a zero/non-finite interocular distance would produce
                # NaN/inf), never a claim that the subject failed
                # liveness. Raised, never silently produced as a
                # corrupted score.
                raise CapabilityUnavailableError(LivenessReasonCode.DEGENERATE_LANDMARKS.value)
            normalized_displacements.append(raw_displacement / interocular_avg)

        mean_displacement = sum(normalized_displacements) / len(normalized_displacements)
        return max(0.0, min(1.0, mean_displacement / _DISPLACEMENT_CALIBRATION))
