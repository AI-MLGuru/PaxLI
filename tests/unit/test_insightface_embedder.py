"""BD-001 Slice D: InsightFaceEmbedder's own decode/cardinality/
representation-validation logic, exercised via the `app=` injection seam
so this stays a fast, hermetic unit test -- it never constructs a real
FaceAnalysis pipeline. Real, end-to-end InsightFace behavior (bbox,
det_score, normed_embedding) was already confirmed live for Slices B/C/
TD-001's own benchmark; this file tests the embedding-specific
translation/validation logic built on top of that same, already-validated
vendor shape.
"""

from typing import Any

import cv2
import numpy as np
import pytest

from core.evidence_result.models import ModelReference
from core.face.capabilities import CapabilityUnavailableError
from core.face.reason_codes import FaceReasonCode
from core.face.types import FaceEmbeddingOutcome
from infrastructure.face.insightface_adapter import (
    _NORM_TOLERANCE,
    InsightFaceEmbedder,
)


def _real_image_bytes() -> bytes:
    array = np.full((20, 20, 3), 200, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", array)
    assert ok
    return bytes(encoded)


def _unit_vector(dimensions: int = 512, norm: float = 1.0) -> np.ndarray:
    """A one-hot vector scaled to an exact, controllable norm -- lets
    boundary tests hit precise norm values rather than approximations.

    float64, not float32: confirmed live that float32's own representable
    precision near 1.001 rounds to 1.0010000467..., enough excess to flip
    an exact-boundary comparison against a 1e-3 tolerance -- a test
    fixture precision artifact, not a property of the adapter under test
    (which works on whatever array it's given, regardless of dtype; real
    InsightFace embeddings are float32, but that's the vendor's own
    concern, not something this test needs to reproduce to exercise the
    adapter's validation logic)."""
    vec = np.zeros(dimensions, dtype=np.float64)
    vec[0] = norm
    return vec


class _FakeFace:
    def __init__(self, embedding: np.ndarray, normed_embedding: np.ndarray) -> None:
        # Deliberately distinct attributes, mirroring the real vendor
        # object -- lets tests prove normed_embedding is what's actually
        # used, not embedding.
        self.embedding = embedding
        self.normed_embedding = normed_embedding


class _FakeApp:
    def __init__(self, faces: list[_FakeFace]) -> None:
        self._faces = faces
        self.call_count = 0

    def get(self, image: Any) -> list[_FakeFace]:
        self.call_count += 1
        return self._faces


@pytest.mark.asyncio
async def test_embed_reports_unreadable_for_undecodable_bytes_without_calling_get() -> None:
    fake = _FakeApp([_FakeFace(embedding=_unit_vector(norm=19.0), normed_embedding=_unit_vector())])
    embedder = InsightFaceEmbedder(app=fake)
    result = await embedder.embed(b"not an image at all, just random bytes")
    assert result.outcome is FaceEmbeddingOutcome.UNREADABLE
    assert result.embedding is None
    assert result.embedding_dimensions is None
    assert result.model_reference is None
    assert fake.call_count == 0


@pytest.mark.asyncio
async def test_embed_reports_no_face_for_zero_faces() -> None:
    embedder = InsightFaceEmbedder(app=_FakeApp([]))
    result = await embedder.embed(_real_image_bytes())
    assert result.outcome is FaceEmbeddingOutcome.NO_FACE
    assert result.embedding is None
    assert result.model_reference is None


@pytest.mark.asyncio
async def test_embed_reports_ambiguous_for_multiple_faces_without_selecting_one() -> None:
    faces = [
        _FakeFace(embedding=_unit_vector(norm=19.0), normed_embedding=_unit_vector()),
        _FakeFace(embedding=_unit_vector(norm=19.0), normed_embedding=_unit_vector()),
    ]
    embedder = InsightFaceEmbedder(app=_FakeApp(faces))
    result = await embedder.embed(_real_image_bytes())
    assert result.outcome is FaceEmbeddingOutcome.AMBIGUOUS
    assert result.embedding is None
    assert result.model_reference is None


@pytest.mark.asyncio
async def test_embed_reports_valid_with_full_model_reference() -> None:
    fake = _FakeApp(
        [_FakeFace(embedding=_unit_vector(norm=19.47), normed_embedding=_unit_vector())]
    )
    embedder = InsightFaceEmbedder(app=fake)
    result = await embedder.embed(_real_image_bytes())
    assert result.outcome is FaceEmbeddingOutcome.VALID
    assert result.embedding is not None
    assert len(result.embedding) == 512
    assert result.embedding_dimensions == 512
    assert result.model_reference is not None
    assert isinstance(result.model_reference, ModelReference)
    assert result.model_reference.model_id == "insightface/buffalo_l/w600k_r50"
    assert result.model_reference.model_version == "buffalo_l"
    assert result.model_reference.runtime == "onnxruntime"
    assert result.model_reference.runtime_version  # non-empty, read from onnxruntime itself


@pytest.mark.asyncio
async def test_embed_uses_normed_embedding_never_raw_embedding() -> None:
    """The raw `embedding` attribute is deliberately given a norm (19.0)
    that would fail validation if it were ever used -- this test passes
    only if the adapter reads `normed_embedding`, confirming D-3
    directly rather than by code inspection alone."""
    fake = _FakeApp(
        [_FakeFace(embedding=_unit_vector(norm=19.0), normed_embedding=_unit_vector(norm=1.0))]
    )
    embedder = InsightFaceEmbedder(app=fake)
    result = await embedder.embed(_real_image_bytes())
    assert result.outcome is FaceEmbeddingOutcome.VALID


@pytest.mark.asyncio
async def test_embed_raises_for_wrong_dimensionality() -> None:
    wrong_dim = _unit_vector(256, norm=1.0)
    fake = _FakeApp([_FakeFace(embedding=_unit_vector(256, norm=19.0), normed_embedding=wrong_dim)])
    embedder = InsightFaceEmbedder(app=fake)
    with pytest.raises(CapabilityUnavailableError) as exc_info:
        await embedder.embed(_real_image_bytes())
    assert exc_info.value.reason_code == FaceReasonCode.EMBEDDING_INVALID_REPRESENTATION.value


@pytest.mark.asyncio
async def test_embed_raises_for_non_finite_values() -> None:
    bad = _unit_vector()
    bad[10] = np.nan
    fake = _FakeApp([_FakeFace(embedding=_unit_vector(norm=19.0), normed_embedding=bad)])
    embedder = InsightFaceEmbedder(app=fake)
    with pytest.raises(CapabilityUnavailableError) as exc_info:
        await embedder.embed(_real_image_bytes())
    assert exc_info.value.reason_code == FaceReasonCode.EMBEDDING_INVALID_REPRESENTATION.value


@pytest.mark.asyncio
async def test_embed_raises_for_zero_vector() -> None:
    zero = np.zeros(512, dtype=np.float32)
    fake = _FakeApp([_FakeFace(embedding=_unit_vector(norm=19.0), normed_embedding=zero)])
    embedder = InsightFaceEmbedder(app=fake)
    with pytest.raises(CapabilityUnavailableError) as exc_info:
        await embedder.embed(_real_image_bytes())
    assert exc_info.value.reason_code == FaceReasonCode.EMBEDDING_INVALID_REPRESENTATION.value


@pytest.mark.asyncio
async def test_embed_accepts_norm_exactly_at_tolerance_boundary() -> None:
    """1.0 + _NORM_TOLERANCE, exactly -- the documented boundary is
    inclusive (`abs(norm - 1.0) > _NORM_TOLERANCE` fails, not >=)."""
    at_boundary = _unit_vector(norm=1.0 + _NORM_TOLERANCE)
    fake = _FakeApp([_FakeFace(embedding=_unit_vector(norm=19.0), normed_embedding=at_boundary)])
    embedder = InsightFaceEmbedder(app=fake)
    result = await embedder.embed(_real_image_bytes())
    assert result.outcome is FaceEmbeddingOutcome.VALID


@pytest.mark.asyncio
async def test_embed_rejects_norm_just_past_tolerance_boundary() -> None:
    just_over = _unit_vector(norm=1.0 + _NORM_TOLERANCE + 1e-6)
    fake = _FakeApp([_FakeFace(embedding=_unit_vector(norm=19.0), normed_embedding=just_over)])
    embedder = InsightFaceEmbedder(app=fake)
    with pytest.raises(CapabilityUnavailableError) as exc_info:
        await embedder.embed(_real_image_bytes())
    assert exc_info.value.reason_code == FaceReasonCode.EMBEDDING_INVALID_REPRESENTATION.value


@pytest.mark.asyncio
async def test_embed_rejects_norm_just_below_tolerance_boundary() -> None:
    just_under = _unit_vector(norm=1.0 - _NORM_TOLERANCE - 1e-6)
    fake = _FakeApp([_FakeFace(embedding=_unit_vector(norm=19.0), normed_embedding=just_under)])
    embedder = InsightFaceEmbedder(app=fake)
    with pytest.raises(CapabilityUnavailableError) as exc_info:
        await embedder.embed(_real_image_bytes())
    assert exc_info.value.reason_code == FaceReasonCode.EMBEDDING_INVALID_REPRESENTATION.value
