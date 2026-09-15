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
