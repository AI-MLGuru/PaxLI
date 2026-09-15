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

from core.evidence_result.models import ModelReference

__all__ = [
    "DocumentFaceExtractionOutcome",
    "DocumentFaceExtractionResult",
    "FaceDetection",
    "FaceDetectionOutcome",
    "FaceEmbedding",
    "FaceEmbeddingOutcome",
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


class FaceEmbeddingOutcome(StrEnum):
    """Slice D's outcome vocabulary -- the same cardinality question
    recurs a third time, for the same reason: `FaceEmbedder` is
    independently callable on raw bytes (DP-001 Decision 3), so it must
    establish for itself whether exactly one quality-assessable subject
    exists. `FaceEmbedder` never selects among multiple detected faces,
    the same BP Decision B-2 boundary already enforced in
    `FaceDetectionOutcome`/`FaceQualityOutcome`."""

    UNREADABLE = "UNREADABLE"  # image bytes could not be decoded
    NO_FACE = "NO_FACE"  # decoded; zero faces -- no subject to embed
    AMBIGUOUS = "AMBIGUOUS"  # decoded; 2+ faces -- no selection, ever
    VALID = "VALID"  # exactly one face; a validated embedding exists


@dataclass(frozen=True)
class FaceEmbedding:
    """Returned by FaceEmbedder.embed() -- always populated, never None,
    mirroring FaceDetection/FaceQuality's own non-optional contract.
    `embedding`/`embedding_dimensions`/`model_reference` are populated
    together iff outcome=VALID, None otherwise -- BD-001 Slice D's own
    explicit requirement: never construct a partially-valid biometric
    representation and leave downstream code to figure out whether it's
    trustworthy. All three fields (or none) -- there is no state where
    only some are set.

    `model_reference` is `core.evidence_result.models.ModelReference`,
    reused directly rather than duplicated -- BD-001 Slice D's own
    reconciliation, grounded in an existing precedent
    (`core.decision.evaluator`/`core.decision.models` already import
    this exact type from `core.evidence_result.models`, so it already
    functions as shared cross-domain identity vocabulary, not a
    persistence-only concept). Carrying the FULL `ModelReference` (all
    five fields), not just `model_id`/`model_version`, is deliberate:
    BP-001.5 Decision 19's compatibility check is
    `reference.model_reference == probe.model_reference` in full --
    duplicating only two fields would let two embeddings from
    genuinely different runtimes/configurations pass as "compatible"
    on a coincidental model_id/model_version match."""

    outcome: FaceEmbeddingOutcome
    embedding: tuple[float, ...] | None
    embedding_dimensions: int | None
    model_reference: ModelReference | None


class DocumentFaceExtractionOutcome(StrEnum):
    """BD-001.2 D-2: named to match its three siblings above
    (FaceDetectionOutcome/FaceQualityOutcome/FaceEmbeddingOutcome)
    exactly -- UNREADABLE/NO_FACE/AMBIGUOUS/VALID, the same
    "couldn't read the bytes / no subject / no single subject / a
    validated result exists" vocabulary this file already uses three
    times. Deliberately NOT named RESOLVED for the positive member --
    that is `core.face.reference.ReferenceAcquisitionOutcome`'s own
    vocabulary one layer up; `DocumentBoundReferenceResolver`'s
    translation table is exactly where that vocabulary shift belongs,
    not this type.

    No selection among 2+ candidates, ever, the same BP Decision B-2
    boundary already enforced by every other face domain type: 2, 3,
    or 10 detected faces in a document image all mean AMBIGUOUS."""

    UNREADABLE = "UNREADABLE"  # image bytes could not be decoded
    NO_FACE = "NO_FACE"  # decoded; zero faces -- nothing to extract
    AMBIGUOUS = "AMBIGUOUS"  # decoded; 2+ faces -- no selection, ever
    VALID = "VALID"  # exactly one face; cropped


@dataclass(frozen=True)
class DocumentFaceExtractionResult:
    """Returned by DocumentFaceExtractor.extract_candidate() -- always
    populated, never None, mirroring every other face domain type's
    non-optional contract. `image` is populated iff outcome=VALID, None
    otherwise -- the same "populated iff not the negative outcome"
    discipline this file uses throughout.

    `image` is the cropped face region only, re-encoded bytes -- never
    the original document image, and never a bounding box/geometry
    (BD-001.1 G-3: nothing outside DocumentFaceExtractor's own adapter
    implementation ever needs the crop coordinates themselves)."""

    outcome: DocumentFaceExtractionOutcome
    image: bytes | None
