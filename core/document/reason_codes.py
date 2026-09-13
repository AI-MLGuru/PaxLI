"""Evidence-level reason codes (Part III §3.14) this document-processing
slice actually produces.

DP-001 Open Question 3 ("where do evidence-level reason codes live in
code") remains genuinely open -- no canonical home or namespace
convention (e.g. an `EVIDENCE:` prefix mirroring EngineReasonCode's
`ENGINE:` and core.policy.reason_codes's `POLICY:`) has been decided.
This module extends Phase 1's narrow, minimal instance of that open
question (DP-003 Decision 3), not its resolution: it defines only the
codes this project's own capabilities and DocumentProcessor actually
emit, using bare names with no invented namespace prefix.
"""

from enum import StrEnum


class DocumentReasonCode(StrEnum):
    DOCUMENT_UNSUPPORTED = "DOCUMENT_UNSUPPORTED"
    IMAGE_TOO_BLURRY = "IMAGE_TOO_BLURRY"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    # DP-002 reconciliation amendment: more than one eligible DOCUMENT
    # capture is a genuine ambiguity, not an infrastructure failure and
    # not a judged negative result -- Part III's own constitutional
    # principle ("PaxLI must never infer certainty from ambiguity")
    # applies directly.
    AMBIGUOUS_DOCUMENT_CAPTURE = "AMBIGUOUS_DOCUMENT_CAPTURE"
    # DP-003 Decision 3 (Phase 2): distinct codes per distinguishable MRZ/
    # barcode failure mode -- "couldn't see it" / "couldn't parse it" /
    # "parsed it but it's wrong" must stay distinguishable, not collapsed.
    MRZ_UNREADABLE = "MRZ_UNREADABLE"
    MRZ_MALFORMED = "MRZ_MALFORMED"
    MRZ_CHECK_DIGIT_MISMATCH = "MRZ_CHECK_DIGIT_MISMATCH"
    BARCODE_UNREADABLE = "BARCODE_UNREADABLE"
    BARCODE_PAYLOAD_UNRECOGNIZED = "BARCODE_PAYLOAD_UNRECOGNIZED"
    BARCODE_PAYLOAD_MALFORMED = "BARCODE_PAYLOAD_MALFORMED"
