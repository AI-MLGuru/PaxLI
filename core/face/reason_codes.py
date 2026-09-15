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

    # BD-001 Slice G (BD-001.2 D-1/D-2): DocumentFaceExtractionOutcome's
    # three non-VALID outcomes, mirroring Slice C/D's own
    # distinguishable-facts discipline exactly. Pre-declared here for a
    # future BiometricProcessor (Slice G.2) to consume -- Slice G's own
    # DocumentBoundReferenceResolver never persists an evidence row and
    # so never actually attaches these to anything yet, the same
    # "declared ahead of its real consumer" pattern DETECTION_UNREADABLE
    # itself followed in Slice B.
    EXTRACTION_UNREADABLE = "EXTRACTION_UNREADABLE"
    EXTRACTION_NO_FACE = "EXTRACTION_NO_FACE"
    EXTRACTION_AMBIGUOUS = "EXTRACTION_AMBIGUOUS"

    # BD-001 Slice G: a face WAS reported by DocumentFaceExtractor's own
    # internal detection call, but its bbox clips to zero/negative width
    # or height against the image -- the same genuine capability-level
    # anomaly category as QUALITY_DEGENERATE_CROP, given its own code
    # rather than reused, per this module's own sub-capability-prefixed
    # discipline. Used with CapabilityUnavailableError, never returned
    # as a DocumentFaceExtractionOutcome.
    EXTRACTION_DEGENERATE_CROP = "EXTRACTION_DEGENERATE_CROP"

    # BD-001 Slice G.2 (BD-001.8 §3): pipeline-level FACE_DETECTION_
    # REFERENCE/PROBE outcomes -- distinct from FaceDetectionOutcome's
    # own two-member vocabulary (UNREADABLE/VALID). face_count==0/2+
    # under VALID are diagnosable pipeline facts with no corresponding
    # capability-level outcome member (BD-001.1 G-1: FaceDetection
    # reports cardinality as observed, carries no verdict) -- these two
    # codes exist at the persistence-mapping layer only, mirroring
    # QUALITY_NO_FACE/QUALITY_AMBIGUOUS's own naming, filling the
    # previously-unused DETECTION_ prefix slot Slice B never needed.
    DETECTION_NO_FACE = "DETECTION_NO_FACE"
    DETECTION_AMBIGUOUS = "DETECTION_AMBIGUOUS"

    # BD-001 Slice G.2 (BD-001.7 G.2-S1): bare, mirroring
    # core.document.reason_codes.DocumentReasonCode's own
    # AMBIGUOUS_DOCUMENT_CAPTURE convention -- applied uniformly across
    # all three probe stages (FACE_DETECTION_PROBE/FACE_QUALITY_PROBE/
    # FACE_EMBEDDING_PROBE), never a per-stage code, since 2+ SELFIE
    # captures is a single precondition failure shared by all three.
    AMBIGUOUS_SELFIE_CAPTURE = "AMBIGUOUS_SELFIE_CAPTURE"

    # BD-001 Slice G.2 (BD-001.7 G.2-S11): reference-ACQUISITION failure
    # reason codes, persisted on FACE_DETECTION_REFERENCE only --
    # explicitly NOT claims that FaceDetector.detect() was ever invoked
    # or returned a corresponding FaceDetectionOutcome. They describe
    # DocumentFaceExtractor's own extraction outcome (surfaced through
    # ReferenceSourceResolver.resolve()), one layer upstream of the
    # generic detection capability -- the same deliberate divergence
    # between capability vocabulary and pipeline-boundary evidence
    # vocabulary already established for EXTRACTION_*/DETECTION_NO_FACE
    # above, restated explicitly here because the stakes (a future
    # implementer adding a synthetic FaceDetector.detect() call merely
    # to make this evidence type "purely" capability-derived) are real.
    REFERENCE_NO_FACE_FOUND = "REFERENCE_NO_FACE_FOUND"
    REFERENCE_AMBIGUOUS = "REFERENCE_AMBIGUOUS"

    # BD-001 Slice G.2 (BD-001.7 G.2-7/G.2-9): FACE_MATCH invalidation --
    # an existing effective match whose current parent(s) are no longer
    # usable for comparison (BD-001.8 §8's lineage-consistency check
    # found either side stale, missing, or non-PASS). Bare, not
    # sub-capability-prefixed: FaceMatcher itself has no
    # CapabilityUnavailableError-shaped failure at all (pure
    # computation), so this is purely a BiometricProcessor-level
    # pipeline fact, the same category as AMBIGUOUS_SELFIE_CAPTURE.
    PARENT_EVIDENCE_NOT_USABLE = "PARENT_EVIDENCE_NOT_USABLE"
