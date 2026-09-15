"""Evidence-level reason codes this liveness capability actually
produces -- mirrors core.face.reason_codes/core.document.reason_codes's
own stated discipline exactly: "where do evidence-level reason codes
live in code" remains genuinely open project-wide (DP-001 Open
Question 3, still unresolved), so this module extends that same narrow,
minimal instance of the open question rather than resolving it -- bare
names, no invented namespace prefix.

Not sub-capability-prefixed (unlike FaceReasonCode's DETECTION_*/
QUALITY_*/EMBEDDING_* members): this domain has exactly one capability
today, so a prefix would add no disambiguation value.
"""

from enum import StrEnum


class LivenessReasonCode(StrEnum):
    # LivenessOutcome's four non-VALID members -- kept distinguishable
    # rather than collapsed, the same "couldn't see it / couldn't parse
    # it / parsed it but it's wrong" discipline DP-003 Decision 3
    # established for MRZ/Barcode, extended to a frame sequence.
    UNREADABLE = "UNREADABLE"
    INSUFFICIENT_FRAMES = "INSUFFICIENT_FRAMES"
    NO_FACE = "NO_FACE"
    AMBIGUOUS = "AMBIGUOUS"

    # BD-001 Slice F: every frame individually passed its own checks
    # (decodable, exactly one face), but the landmarks that face
    # produced are degenerate (e.g. zero interocular distance) --
    # dividing by that would produce NaN/inf, not a meaningful score.
    # A provider/runtime failure to safely compute the heuristic, never
    # a claim that the subject failed liveness. Used with
    # CapabilityUnavailableError, never returned as a LivenessOutcome.
    DEGENERATE_LANDMARKS = "DEGENERATE_LANDMARKS"
