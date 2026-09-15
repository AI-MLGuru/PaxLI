"""BD-001 Slice F: InsightFaceLivenessProvider's own decode/cardinality/
scan-order/normalization logic, exercised via the `app=` injection seam
so this stays a fast, hermetic unit test -- it never constructs a real
FaceAnalysis pipeline. Real, end-to-end InsightFace behavior (kps
ordering, confirmed live as [left_eye, right_eye, nose, left_mouth,
right_mouth]) was verified separately against the actual installed
model before this adapter was written.
"""

from typing import Any

import cv2
import numpy as np
import pytest

from core.liveness.exceptions import CapabilityUnavailableError
from core.liveness.provider import LivenessOutcome
from core.liveness.reason_codes import LivenessReasonCode
from infrastructure.liveness.insightface_provider import InsightFaceLivenessProvider


def _real_frame_bytes() -> bytes:
    array = np.full((20, 20, 3), 200, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", array)
    assert ok
    return bytes(encoded)


def _kps(eye_gap: float = 50.0, shift: float = 0.0) -> np.ndarray:
    """A plausible 5-point landmark set (left_eye, right_eye, nose,
    left_mouth, right_mouth), with a controllable interocular distance
    and a controllable uniform shift (simulating inter-frame movement)."""
    return np.array(
        [
            [100 + shift, 100],
            [100 + eye_gap + shift, 100],
            [100 + eye_gap / 2 + shift, 130],
            [100 + shift, 160],
            [100 + eye_gap + shift, 160],
        ],
        dtype=np.float64,
    )


class _FakeFace:
    def __init__(self, kps: np.ndarray) -> None:
        self.kps = kps


class _FakeApp:
    """Returns a different result on each successive `get()` call, in
    order -- lets tests prove per-frame submission-order scanning
    actually happens, not just that frame 0 is checked."""

    def __init__(self, per_call_faces: list[list[_FakeFace]]) -> None:
        self._per_call_faces = per_call_faces
        self.call_count = 0

    def get(self, image: Any) -> list[_FakeFace]:
        result = self._per_call_faces[self.call_count]
        self.call_count += 1
        return result


@pytest.mark.asyncio
async def test_assess_reports_insufficient_frames_for_zero_frames_without_calling_get() -> None:
    fake = _FakeApp([])
    provider = InsightFaceLivenessProvider(app=fake)
    result = await provider.assess([])
    assert result.outcome is LivenessOutcome.INSUFFICIENT_FRAMES
    assert result.live_score is None
    assert result.attack_score is None
    assert fake.call_count == 0


@pytest.mark.asyncio
async def test_assess_reports_insufficient_frames_for_one_frame_without_calling_get() -> None:
    fake = _FakeApp([[_FakeFace(kps=_kps())]])
    provider = InsightFaceLivenessProvider(app=fake)
    result = await provider.assess([_real_frame_bytes()])
    assert result.outcome is LivenessOutcome.INSUFFICIENT_FRAMES
    assert fake.call_count == 0


@pytest.mark.asyncio
async def test_assess_reports_unreadable_for_first_frame_undecodable() -> None:
    fake = _FakeApp([[_FakeFace(kps=_kps())], [_FakeFace(kps=_kps())]])
    provider = InsightFaceLivenessProvider(app=fake)
    result = await provider.assess([b"garbage", _real_frame_bytes()])
    assert result.outcome is LivenessOutcome.UNREADABLE
    assert fake.call_count == 0  # decode failure caught before any get() call


@pytest.mark.asyncio
async def test_assess_reports_unreadable_for_second_frame_undecodable() -> None:
    """Proves per-frame scanning happens in submission order -- the
    problem is on frame 2, not frame 1."""
    fake = _FakeApp([[_FakeFace(kps=_kps())]])
    provider = InsightFaceLivenessProvider(app=fake)
    result = await provider.assess([_real_frame_bytes(), b"garbage"])
    assert result.outcome is LivenessOutcome.UNREADABLE
    assert fake.call_count == 1  # frame 1 was processed; frame 2 never reached get()


@pytest.mark.asyncio
async def test_assess_reports_no_face_for_second_frame_with_zero_faces() -> None:
    fake = _FakeApp([[_FakeFace(kps=_kps())], []])
    provider = InsightFaceLivenessProvider(app=fake)
    result = await provider.assess([_real_frame_bytes(), _real_frame_bytes()])
    assert result.outcome is LivenessOutcome.NO_FACE
    assert fake.call_count == 2


@pytest.mark.asyncio
async def test_assess_reports_ambiguous_for_second_frame_with_multiple_faces() -> None:
    fake = _FakeApp([[_FakeFace(kps=_kps())], [_FakeFace(kps=_kps()), _FakeFace(kps=_kps())]])
    provider = InsightFaceLivenessProvider(app=fake)
    result = await provider.assess([_real_frame_bytes(), _real_frame_bytes()])
    assert result.outcome is LivenessOutcome.AMBIGUOUS
    assert fake.call_count == 2


@pytest.mark.asyncio
async def test_assess_reports_valid_with_zero_score_for_no_movement() -> None:
    still = _kps(shift=0.0)
    fake = _FakeApp([[_FakeFace(kps=still)], [_FakeFace(kps=still)]])
    provider = InsightFaceLivenessProvider(app=fake)
    result = await provider.assess([_real_frame_bytes(), _real_frame_bytes()])
    assert result.outcome is LivenessOutcome.VALID
    assert result.live_score == pytest.approx(0.0)
    assert result.attack_score is None
    assert result.signals == ("landmark_displacement",)


@pytest.mark.asyncio
async def test_assess_reports_valid_with_positive_bounded_score_for_movement() -> None:
    # eye_gap=50, shift=1.0 -> raw displacement 1.0, normalized 1.0/50=0.02,
    # live_score = 0.02 / 0.05 (calibration) = 0.4
    fake = _FakeApp([[_FakeFace(kps=_kps(shift=0.0))], [_FakeFace(kps=_kps(shift=1.0))]])
    provider = InsightFaceLivenessProvider(app=fake)
    result = await provider.assess([_real_frame_bytes(), _real_frame_bytes()])
    assert result.outcome is LivenessOutcome.VALID
    assert result.live_score is not None
    assert 0.0 < result.live_score < 1.0
    assert result.live_score == pytest.approx(0.4, abs=1e-6)


@pytest.mark.asyncio
async def test_assess_clamps_large_movement_to_one() -> None:
    fake = _FakeApp([[_FakeFace(kps=_kps(shift=0.0))], [_FakeFace(kps=_kps(shift=50.0))]])
    provider = InsightFaceLivenessProvider(app=fake)
    result = await provider.assess([_real_frame_bytes(), _real_frame_bytes()])
    assert result.outcome is LivenessOutcome.VALID
    assert result.live_score == 1.0


@pytest.mark.asyncio
async def test_assess_raises_for_degenerate_landmarks() -> None:
    """eye_gap=0 -- left and right eye landmarks coincide, making
    interocular distance zero. Every frame individually passes its own
    decode/cardinality checks; the failure is the provider's own
    inability to safely normalize, not a LivenessOutcome."""
    degenerate = _kps(eye_gap=0.0)
    fake = _FakeApp([[_FakeFace(kps=degenerate)], [_FakeFace(kps=degenerate)]])
    provider = InsightFaceLivenessProvider(app=fake)
    with pytest.raises(CapabilityUnavailableError) as exc_info:
        await provider.assess([_real_frame_bytes(), _real_frame_bytes()])
    assert exc_info.value.reason_code == LivenessReasonCode.DEGENERATE_LANDMARKS.value


@pytest.mark.asyncio
async def test_assess_raises_for_non_finite_landmark_coordinate() -> None:
    """A NaN coordinate in one frame's landmarks (a malformed vendor SDK
    result, not anything a real frame's own decode/cardinality checks
    would catch) must never propagate into a corrupted live_score --
    raw_displacement itself must be validated, not only interocular_avg."""
    normal = _kps()
    nan_kps = _kps().copy()
    nan_kps[0, 0] = np.nan
    fake = _FakeApp([[_FakeFace(kps=normal)], [_FakeFace(kps=nan_kps)]])
    provider = InsightFaceLivenessProvider(app=fake)
    with pytest.raises(CapabilityUnavailableError) as exc_info:
        await provider.assess([_real_frame_bytes(), _real_frame_bytes()])
    assert exc_info.value.reason_code == LivenessReasonCode.DEGENERATE_LANDMARKS.value
