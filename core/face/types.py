"""BD-001 Slice B: the domain-level shape a face-processing capability
returns -- never an EvidenceResult, never a Pydantic persistence schema,
mirroring core.document.types's own discipline exactly. A capability
implementation never touches persistence itself; that remains a future
BiometricProcessor's job (BD-001 Slice G.2, not yet built).

`FaceDetection` is deliberately named the same as the original BD-001
Slice B proposal, not `FaceDetectionResult` -- that name is already
taken by core.evidence_result.schemas.FaceDetectionResult (the
persistence-layer payload shape), and core.document's own precedent
(OcrExtractionResult vs. OCRExtraction; MrzResult vs. MRZExtraction)
deliberately keeps the domain and persistence layers under different
class names, in different modules, to avoid exactly this ambiguity.
"""

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "FaceDetection",
    "FaceDetectionOutcome",
    "FaceQuality",
    "FaceQualityOutcome",
]


class FaceDetectionOutcome(StrEnum):
    """Named `FaceDetectionOutcome`, not `FaceReadOutcome` -- a deliberate
    departure from core.document.types's exceptionless `*ReadOutcome`
    convention (OCRReadOutcome/MRZReadOutcome/BarcodeReadOutcome), made
    for a reasoned semantic distinction, not an oversight: those three
    capabilities extract/read content off an image; face detection
    observes presence and cardinality, a categorically different
    question "reading" doesn't honestly describe.

    No FAIL/MALFORMED member exists, mirroring OCRReadOutcome's own
    reasoning (DP-005 Decision 2) -- face detection has no
    standards-defined negative condition and no structural grammar to
    violate; only whether the image itself was processable at all."""

    UNREADABLE = "UNREADABLE"
    VALID = "VALID"


@dataclass(frozen=True)
class FaceDetection:
    """Returned by FaceDetector.detect() -- always populated, never None
    (mirrors OCRReadResult's own non-optional contract: the method
    itself always returns a result object). `detected`/`face_count` are
    None exactly when outcome=UNREADABLE -- populated together, never
    independently, the same "populated iff not the negative outcome"
    discipline core.document.types uses throughout.

    `VALID` does NOT mean "a face was found" -- it means the detection
    operation itself completed successfully. `face_count=0` under
    `VALID` is a legitimate, fully successful result: the image was
    examined and no face is present. This is cardinality as *observed*,
    never as *judged* -- BP-001 §9.4's own frozen principle: "FaceDetection
    reports raw cardinality as observed... a policy/Decision-Engine
    concern, not something the capability itself decides." Whatever
    consumes this value (a future BiometricProcessor, BD-001 Slice G.2)
    owns every judgment about whether a given cardinality is usable --
    this type carries no opinion of its own, deliberately."""

    outcome: FaceDetectionOutcome
    detected: bool | None
    face_count: int | None


class FaceQualityOutcome(StrEnum):
    """Slice C's own outcome vocabulary -- frozen after finding that
    BD-001's original draft language ("quality for the primary face")
    silently assumed a face-selection heuristic, exactly what BP Decision
    B-2 forbids for the probe side. `FaceQualityAssessor` is independently
    callable on raw bytes (DP-001 Decision 3), so it must establish for
    itself whether its input is structurally suitable for a quality
    judgment -- it cannot assume `FaceDetector` already ran, and it must
    never select among multiple candidates to make one up.

    `NO_FACE` and `AMBIGUOUS` are NOT quality judgments ("poor quality")
    -- they mean no single quality-assessable subject exists. That is a
    structural fact (the same category as MRZParser.parse() returning
    None for "no zone present"), never a policy decision about whether
    verification should proceed with what's available -- that judgment
    belongs entirely to a future BiometricProcessor/the Decision Engine."""

    UNREADABLE = "UNREADABLE"  # image bytes could not be decoded
    NO_FACE = "NO_FACE"  # decoded; zero faces -- quality is inapplicable
    AMBIGUOUS = "AMBIGUOUS"  # decoded; 2+ faces -- no selection, ever
    VALID = "VALID"  # exactly one face; quality assessed


@dataclass(frozen=True)
class FaceQuality:
    """Returned by FaceQualityAssessor.assess() -- always populated,
    never None, mirroring FaceDetection's own non-optional contract.
    `quality_score` is populated iff outcome=VALID; None for every other
    outcome (populated-iff-VALID, the same discipline FaceDetection uses
    for detected/face_count).

    `quality_score` is bounded to [0.0, 1.0], 1.0 = highest quality --
    frozen as an explicit contract, not left implicit in `float`, since
    the persisted schema (core.evidence_result.schemas.FaceQualityResult)
    only says `float` and does not itself constrain the range. This is a
    bounded HEURISTIC score, not a calibrated probability of image
    quality -- an important distinction for whoever evaluates this
    system later, not a formality."""

    outcome: FaceQualityOutcome
    quality_score: float | None
