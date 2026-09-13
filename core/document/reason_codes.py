"""Evidence-level reason codes (Part III §3.14) this Phase 1 slice
actually produces.

DP-001 Open Question 3 ("where do evidence-level reason codes live in
code") remains genuinely open -- no canonical home or namespace
convention (e.g. an `EVIDENCE:` prefix mirroring EngineReasonCode's
`ENGINE:` and core.policy.reason_codes's `POLICY:`) has been decided.
This module is Phase 1's narrow, minimal instance of that open
question, not its resolution: it defines only the codes this phase's
own capabilities and DocumentProcessor actually emit, using bare names
matching exactly how Part III's own text quotes them, with no invented
namespace prefix.
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
