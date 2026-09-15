"""Evidence-level reason codes this face-processing slice actually
produces -- mirrors core.document.reason_codes's own stated discipline
exactly: "where do evidence-level reason codes live in code" remains
genuinely open project-wide (DP-001 Open Question 3, still unresolved),
so this module extends that same narrow, minimal instance of the open
question rather than resolving it -- bare names, no invented namespace
prefix.

Sub-capability-prefixed (`DETECTION_*`), not bare `UNREADABLE`, because
this enum is expected to span multiple face sub-capabilities over time
(detection, matching, eventually more) the same way DocumentReasonCode
spans OCR/MRZ/Barcode/Document with per-sub-capability prefixes
(OCR_UNREADABLE, MRZ_UNREADABLE, BARCODE_UNREADABLE) rather than one
ambiguous shared name.
"""

from enum import StrEnum


class FaceReasonCode(StrEnum):
    # BD-001 Slice B: FaceDetectionOutcome.UNREADABLE's reason code --
    # the image bytes could not be decoded, distinct from a
    # successfully-decoded image with zero faces present (which carries
    # no reason code at all; it is a legitimate PASS with face_count=0).
    DETECTION_UNREADABLE = "DETECTION_UNREADABLE"

    # BD-001 Slice C: FaceQualityOutcome's three non-VALID outcomes, kept
    # distinguishable rather than collapsed -- "couldn't read the bytes,"
    # "no subject present," and "no single subject to assess" are
    # structurally different facts (the same "couldn't see it / couldn't
    # parse it / parsed it but it's wrong" discipline DP-003 Decision 3
    # already established for MRZ/Barcode).
    QUALITY_UNREADABLE = "QUALITY_UNREADABLE"
    QUALITY_NO_FACE = "QUALITY_NO_FACE"
    QUALITY_AMBIGUOUS = "QUALITY_AMBIGUOUS"

    # BD-001 Slice C reconciliation: a face WAS reported, but its bbox
    # clips to zero/negative width or height against the image bounds --
    # not a normal FaceQualityOutcome (no face / ambiguous / unreadable
    # bytes all mean something else), a genuine capability-level anomaly
    # in the detector's own output. Used with CapabilityUnavailableError,
    # never returned as a FaceQuality outcome.
    QUALITY_DEGENERATE_CROP = "QUALITY_DEGENERATE_CROP"

    # BD-001 Slice D: FaceEmbeddingOutcome's three non-VALID outcomes,
    # mirroring Slice C's own distinguishable-facts discipline exactly.
    EMBEDDING_UNREADABLE = "EMBEDDING_UNREADABLE"
    EMBEDDING_NO_FACE = "EMBEDDING_NO_FACE"
    EMBEDDING_AMBIGUOUS = "EMBEDDING_AMBIGUOUS"

    # BD-001 Slice D (D-4): the vendor's own reported "normalized"
    # embedding failed validation (wrong dimensionality, non-finite
    # values, or a norm not sufficiently close to unit length) -- a
    # genuine capability-level anomaly, the same category as
    # QUALITY_DEGENERATE_CROP. Used with CapabilityUnavailableError,
    # never returned as a FaceEmbedding outcome. Explicitly never
    # silently repaired (no re-normalization) -- validated, or rejected.
    EMBEDDING_INVALID_REPRESENTATION = "EMBEDDING_INVALID_REPRESENTATION"

    # BD-001 Slice E: FaceMatchOutcome.compatible=False's reason code --
    # both embeddings are individually VALID (unlike every *_UNREADABLE/
    # *_NO_FACE/*_AMBIGUOUS code above), but their model_reference differs,
    # so no similarity can be safely computed. Means "the representations
    # cannot safely be compared," never "the representations are
    # themselves invalid" (that's EMBEDDING_INVALID_REPRESENTATION) and
    # never "these faces don't match" (compare() makes no such claim --
    # FaceMatcher never returns FAIL). Not used with
    # CapabilityUnavailableError -- FaceMatcher has no such exception at
    # all (pure computation, no vendor/infrastructure dependency); this
    # is a legitimate FaceMatchOutcome value, consumed later by a future
    # BiometricProcessor deciding the persisted EvidenceResultStatus
    # (INCONCLUSIVE, per BP-001.5 Decision 21 -- not decided here, that
    # mapping happens outside FaceMatcher's own scope).
    REPRESENTATION_INCOMPATIBLE = "REPRESENTATION_INCOMPATIBLE"
