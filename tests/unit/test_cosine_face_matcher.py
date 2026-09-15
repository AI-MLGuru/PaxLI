"""BD-001 Slice E: CosineFaceMatcher's own contract -- no injection seam
needed here, unlike the InsightFace-backed adapters (B/C/D): FaceMatcher
has no vendor dependency at all, so tests construct FaceEmbedding/
ModelReference domain objects directly.
"""

import pytest

from core.evidence_result.models import ModelReference
from core.face.matcher import CosineFaceMatcher
from core.face.types import FaceEmbedding, FaceEmbeddingOutcome

_MODEL_A = ModelReference(
    model_id="insightface/buffalo_l/w600k_r50",
    model_version="buffalo_l",
    runtime="onnxruntime",
    runtime_version="1.30.0",
)
# Differs only in runtime_version -- exactly the case BP-001.5 Decision 19
# exists to catch, not something a model_id/model_version-only comparison
# would notice.
_MODEL_B = _MODEL_A.model_copy(update={"runtime_version": "1.29.0"})


def _valid_embedding(values: tuple[float, ...], model_reference: ModelReference) -> FaceEmbedding:
    return FaceEmbedding(
        outcome=FaceEmbeddingOutcome.VALID,
        embedding=values,
        embedding_dimensions=len(values),
        model_reference=model_reference,
    )


def _invalid_embedding(outcome: FaceEmbeddingOutcome) -> FaceEmbedding:
    return FaceEmbedding(
        outcome=outcome, embedding=None, embedding_dimensions=None, model_reference=None
    )


def test_compare_identical_unit_vectors_gives_similarity_one() -> None:
    v = (1.0, 0.0, 0.0)
    reference = _valid_embedding(v, _MODEL_A)
    probe = _valid_embedding(v, _MODEL_A)
    outcome = CosineFaceMatcher().compare(reference=reference, probe=probe)
    assert outcome.compatible is True
    assert outcome.similarity == pytest.approx(1.0)


def test_compare_orthogonal_unit_vectors_gives_similarity_zero() -> None:
    reference = _valid_embedding((1.0, 0.0, 0.0), _MODEL_A)
    probe = _valid_embedding((0.0, 1.0, 0.0), _MODEL_A)
    outcome = CosineFaceMatcher().compare(reference=reference, probe=probe)
    assert outcome.compatible is True
    assert outcome.similarity == pytest.approx(0.0)


def test_compare_opposite_unit_vectors_gives_similarity_negative_one() -> None:
    reference = _valid_embedding((1.0, 0.0, 0.0), _MODEL_A)
    probe = _valid_embedding((-1.0, 0.0, 0.0), _MODEL_A)
    outcome = CosineFaceMatcher().compare(reference=reference, probe=probe)
    assert outcome.compatible is True
    assert outcome.similarity == pytest.approx(-1.0)


def test_compare_clamps_positive_floating_point_overshoot() -> None:
    """compare() does not itself verify normalization (Slice D already
    guarantees it) -- this deliberately artificial vector's own
    dot-product-with-itself exceeds 1.0, exercising the clamp directly
    and deterministically rather than hoping real floating-point noise
    happens to overshoot."""
    v = (1.0000001, 0.0, 0.0)
    reference = _valid_embedding(v, _MODEL_A)
    probe = _valid_embedding(v, _MODEL_A)
    outcome = CosineFaceMatcher().compare(reference=reference, probe=probe)
    assert outcome.compatible is True
    assert outcome.similarity == 1.0


def test_compare_clamps_negative_floating_point_overshoot() -> None:
    reference = _valid_embedding((-1.0000001, 0.0, 0.0), _MODEL_A)
    probe = _valid_embedding((1.0, 0.0, 0.0), _MODEL_A)
    outcome = CosineFaceMatcher().compare(reference=reference, probe=probe)
    assert outcome.compatible is True
    assert outcome.similarity == -1.0


def test_compare_reports_incompatible_for_differing_model_reference_without_computing() -> None:
    """No arithmetic at all when model_reference differs -- proven, not
    just asserted: give the two embeddings vectors whose dot product
    would be a clean 1.0 if computed, so a wrongly-computed similarity
    couldn't accidentally look like None by coincidence."""
    v = (1.0, 0.0, 0.0)
    reference = _valid_embedding(v, _MODEL_A)
    probe = _valid_embedding(v, _MODEL_B)
    outcome = CosineFaceMatcher().compare(reference=reference, probe=probe)
    assert outcome.compatible is False
    assert outcome.similarity is None


def test_compare_raises_for_non_valid_reference() -> None:
    reference = _invalid_embedding(FaceEmbeddingOutcome.NO_FACE)
    probe = _valid_embedding((1.0, 0.0, 0.0), _MODEL_A)
    with pytest.raises(ValueError, match="reference"):
        CosineFaceMatcher().compare(reference=reference, probe=probe)


def test_compare_raises_for_non_valid_probe() -> None:
    reference = _valid_embedding((1.0, 0.0, 0.0), _MODEL_A)
    probe = _invalid_embedding(FaceEmbeddingOutcome.AMBIGUOUS)
    with pytest.raises(ValueError, match="probe"):
        CosineFaceMatcher().compare(reference=reference, probe=probe)
