"""BD-001 Slice E / BP-001.5 Decisions 8, 19, 20, 21: `FaceMatcher` is a
domain comparison operation, deliberately NOT defined in
`core.face.capabilities` (BP Decision 8) -- it shares that module's
domain-result discipline (never a persistence identifier, never an
`EvidenceResultStatus`) but not its `image: bytes -> domain result`
contract shape. Mirrors `core.document.reconciliation.DocumentFieldReconciler`'s
own precedent exactly: pure computation over already-fetched domain
values, no I/O of its own, no vendor/infrastructure dependency, and
therefore no adapter in `infrastructure/face/` at all -- both the ABC
and its one concrete implementation live here, in `core/`, the same as
`DocumentFieldReconciler`'s own concrete stand-in lives in
`core/document/deterministic.py`, never in `infrastructure/`.

`CosineFaceMatcher`, not `DeterministicFaceMatcher`: in this codebase's
own vocabulary, "Deterministic" names a fixture stand-in meant to be
replaced later (`DeterministicOCREngine`, etc.). Cosine similarity over
L2-normalized embeddings is not a placeholder -- it is the real
algorithm production face-matching systems use. Naming it
"Deterministic" would misdescribe genuine math as a temporary fake.

Scope, narrower than it might look: `compare()` receives two
`FaceEmbedding` DOMAIN objects, never `EvidenceResult` rows, IDs, or
reason codes. BP-001.5 Decision 20's `reference_evidence_result_id`/
`probe_evidence_result_id` fields belong entirely to the *persisted*
`FaceMatchResult` schema, built later by a future `BiometricProcessor`
that actually has those IDs -- `FaceMatcher` structurally cannot carry
them, by design, and does not try to.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.face.types import FaceEmbedding, FaceEmbeddingOutcome

# Cosine similarity of two unit vectors is mathematically bounded to
# [-1.0, 1.0] -- NOT [0.0, 1.0] like FaceQuality.quality_score. A real,
# easy-to-miss distinction, frozen explicitly rather than left implicit.
_SIMILARITY_MIN = -1.0
_SIMILARITY_MAX = 1.0


@dataclass(frozen=True)
class FaceMatchOutcome:
    """`similarity` is populated iff `compatible=True`; `None` otherwise
    -- the same "populated iff not the negative case" discipline every
    other face domain type in this project uses. When populated, always
    within [-1.0, 1.0] -- the matcher MUST ensure this; a tiny
    floating-point overshoot from the dot-product arithmetic may be
    clamped to the interval, but this is bounding a valid computation's
    own numerical noise, never "correcting" an invalid embedding (Slice
    D's own D-4 gate already guarantees the embeddings themselves are
    valid before they ever reach this type).

    `FaceMatcher` makes no claim beyond this -- `compatible=True` with a
    low `similarity` is still a fully successful comparison, not a
    judgment that the two faces don't match. Whether a given similarity
    value constitutes "a match" is exclusively a future Decision Engine
    policy question (DEC-5.14's own worked example:
    `FaceMatch.similarity >= calibrated_threshold`), never something
    this type or `FaceMatcher` decides."""

    compatible: bool
    similarity: float | None


class FaceMatcher(ABC):
    """Deliberately independent of `FaceDetector`/`FaceQualityAssessor`/
    `FaceEmbedder` -- no import, no constructor dependency, the same
    DP-001 Decision 3 boundary already applied three times over in
    `core.face.capabilities`."""

    @abstractmethod
    def compare(self, *, reference: FaceEmbedding, probe: FaceEmbedding) -> FaceMatchOutcome:
        """Synchronous, not async -- pure computation over already-
        fetched domain values, no I/O of its own, mirroring
        `DocumentFieldReconciler.reconcile()`'s own sync contract exactly
        (and for the same reason: there is no `CapabilityUnavailableError`-
        shaped failure mode here either).

        Raises `ValueError` if either `reference.outcome` or
        `probe.outcome` is not `FaceEmbeddingOutcome.VALID` -- a caller-
        precondition violation (whoever calls `compare()` must confirm
        both sides are `VALID` first), never treated as
        `compatible=False`. Conflating "caller passed something it
        should never have passed" with "these two valid representations
        can't be compared" would hide a real bug behind the same signal
        a legitimate model mismatch uses.

        `compatible=False`, `similarity=None` when
        `reference.model_reference != probe.model_reference` (BP-001.5
        Decision 19 point 2) -- no arithmetic is attempted at all in
        that case. Never re-normalizes either embedding; both are
        already guaranteed unit-norm by `FaceEmbedder`'s own D-4
        validation before ever reaching this method."""
        raise NotImplementedError


class CosineFaceMatcher(FaceMatcher):
    """The real algorithm, not a stand-in -- cosine similarity between
    two L2-normalized embeddings reduces to a plain dot product
    (`cosine_sim(a, b) = dot(a, b) / (|a|*|b|) = dot(a, b)` when
    `|a|=|b|=1`), relying explicitly on `FaceEmbedder`'s own upstream
    guarantee rather than re-deriving or re-validating normalization
    here -- that would duplicate a responsibility Slice D already owns."""

    def compare(self, *, reference: FaceEmbedding, probe: FaceEmbedding) -> FaceMatchOutcome:
        if reference.outcome is not FaceEmbeddingOutcome.VALID:
            raise ValueError(
                f"reference embedding is not VALID (outcome={reference.outcome!r}) -- "
                "callers must confirm both sides are VALID before calling compare()"
            )
        if probe.outcome is not FaceEmbeddingOutcome.VALID:
            raise ValueError(
                f"probe embedding is not VALID (outcome={probe.outcome!r}) -- "
                "callers must confirm both sides are VALID before calling compare()"
            )

        if reference.model_reference != probe.model_reference:
            return FaceMatchOutcome(compatible=False, similarity=None)

        # mypy narrows outcome==VALID above but not embedding's own
        # optionality -- VALID implies embedding is populated, per
        # FaceEmbedding's own frozen "populated together iff VALID"
        # contract, confirmed structurally by FaceEmbedder, not
        # re-validated here.
        assert reference.embedding is not None
        assert probe.embedding is not None

        dot_product = sum(r * p for r, p in zip(reference.embedding, probe.embedding, strict=True))
        similarity = max(_SIMILARITY_MIN, min(_SIMILARITY_MAX, dot_product))

        return FaceMatchOutcome(compatible=True, similarity=similarity)
