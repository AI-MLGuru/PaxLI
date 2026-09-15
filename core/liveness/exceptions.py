"""Defined locally rather than imported from `core.face.capabilities` or
`core.document.capabilities`: each domain owns its own capability-port
exception, the same domain-separation discipline `core/face/`,
`core/document/`, `core/liveness/` already keep as distinct packages.
"""


class CapabilityUnavailableError(Exception):
    """Raised for a known, expected, self-diagnosed failure that a future
    BiometricProcessor would translate into a stage-level UNAVAILABLE
    EvidenceResult -- mirrors core.face.capabilities.CapabilityUnavailableError's
    own docstring and the DP-002 reconciliation amendment exactly.

    Explicitly NOT this: any of LivenessOutcome's own members (those are
    legitimate domain results, not capability/infrastructure failures).
    A degenerate-landmark condition (e.g. zero interocular distance,
    which would make the normalization step divide by zero) IS this --
    the provider/runtime cannot safely compute the result, which is a
    different claim from "the subject failed liveness." Any OTHER
    exception -- a bug, an invariant violation, a configuration error --
    is not this project's business to reinterpret as ordinary capability
    unavailability; it propagates uncaught."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
