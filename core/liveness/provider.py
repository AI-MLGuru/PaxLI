"""BD-001 Slice F: `LivenessProvider`'s own contract shape (`frames:
list[bytes] -> LivenessEvidence`) is reused, not replaced -- BP-001 §1
already distinguished it from the rejected `FaceProvider`: its problem
was never internal bundling, only that nothing in the capture layer
produced the `list[bytes]` it expects. `LivenessEvidence` had the same
gap every other face domain type originally had (`FaceDetection`/
`FaceQuality`/`FaceEmbedding` before Slices B/C/D): no outcome
vocabulary distinguishing "couldn't process this input" from "processed
it and it wasn't usable." Extended here rather than replaced, matching
the "smallest coherent change" this project's own workflow discipline
prefers.

Explicitly a "Temporal Liveness Demo" / "Liveness Heuristic Demo" (BD-001
Slice F's own frozen terminology requirement) -- inter-frame landmark
displacement is a weak signal, defeated by a replayed video (real
landmark movement, not a live capture) and prone to false positives from
hand tremor holding a static photo. It catches only the crudest
motionless-photo presentation attack. This is stated here, at the point
of computation, not only in a later API/frontend layer -- the terminology
rule exists specifically so this capability is never mistaken for
production presentation-attack detection.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

__all__ = ["LivenessEvidence", "LivenessOutcome", "LivenessProvider"]


class LivenessOutcome(StrEnum):
    """`INSUFFICIENT_FRAMES` is a sequence-level precondition (a property
    of the frame COUNT alone, checked before any frame's content is
    touched) -- it never competes with the other three, which are
    per-frame processing outcomes evaluated by scanning frames in
    submission order and stopping at the first frame with any problem.
    There is no global severity ranking between UNREADABLE/NO_FACE/
    AMBIGUOUS: whichever of the three a given frame actually exhibits is
    what gets reported, determined by scan order, not by an abstract
    claim that one is "worse" than another (BD-001 Slice F's own
    reconciliation -- deliberately not the OCR/MRZ/Barcode `*ReadOutcome`
    pattern of a fixed precedence, because this is a genuinely different
    kind of outcome space: per-frame facts about a sequence, not a single
    document's own structural grammar)."""

    UNREADABLE = "UNREADABLE"  # a frame's bytes could not be decoded
    INSUFFICIENT_FRAMES = "INSUFFICIENT_FRAMES"  # fewer than 2 frames submitted
    NO_FACE = "NO_FACE"  # a frame had zero detectable faces
    AMBIGUOUS = "AMBIGUOUS"  # a frame had 2+ detectable faces
    VALID = "VALID"  # every frame had exactly one face; the temporal heuristic was computed


@dataclass(frozen=True)
class LivenessEvidence:
    """Returned by LivenessProvider.assess() -- always populated, never
    None, mirroring every other face-domain capability's non-optional
    contract. `live_score`/`signals` are populated iff outcome=VALID,
    None/() otherwise -- the same "populated iff not the negative case"
    discipline used throughout.

    `attack_score` is ALWAYS None for this demo heuristic -- intentional,
    not "not implemented by accident." Inter-frame landmark displacement
    measures MOVEMENT, not attack characteristics (texture, replay
    artifacts, challenge-response). Populating attack_score from a signal
    that was never designed to detect attacks would claim a capability
    this implementation does not have. The persisted
    LivenessAssessmentResult schema already anticipates this: `live_score`
    is required, `attack_score` is optional (core/evidence_result/
    schemas.py) -- this decision fits the existing contract rather than
    working around it.

    `signals` names which heuristics contributed -- `("landmark_displacement",)`
    when VALID, making the score self-describing (a future consumer can
    see what actually produced it) at zero cost, since the field already
    existed, unused, before this reconciliation."""

    outcome: LivenessOutcome
    live_score: float | None
    attack_score: float | None
    signals: tuple[str, ...] = ()


class LivenessProvider(ABC):
    """Contract for liveness assessment. The one implementation in this
    project (BD-001 Slice F, `InsightFaceLivenessProvider`) is explicitly
    a demo heuristic, never production presentation-attack detection --
    see this module's own docstring."""

    @abstractmethod
    async def assess(self, frames: list[bytes]) -> LivenessEvidence:
        """Always returns a populated LivenessEvidence -- never None.
        `len(frames) < 2` is checked first, unconditionally, before any
        frame's bytes are touched (INSUFFICIENT_FRAMES -- there is no
        pair of frames to compute a displacement from). Otherwise, frames
        are scanned in submission order; the first frame that cannot be
        decoded, or that has zero or 2+ detected faces, determines the
        outcome (UNREADABLE / NO_FACE / AMBIGUOUS respectively) and
        processing stops there -- later frames are never inspected once
        a definitive negative outcome is found. `VALID` requires every
        submitted frame to contain exactly one detectable face.

        May raise `CapabilityUnavailableError` (core.liveness.exceptions)
        if the underlying computation cannot be safely performed even
        though every frame individually passed the checks above (e.g.
        degenerate/zero-distance landmarks that would make the
        normalization step divide by zero) -- a provider/runtime failure,
        never a `LivenessOutcome`. This distinction matters: a degenerate-
        landmark failure does NOT mean the subject failed liveness: it
        means the provider could not safely compute the heuristic at
        all."""
        raise NotImplementedError
