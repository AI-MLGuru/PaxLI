from typing import Protocol


class EvidenceSchemaCatalog(Protocol):
    """Domain-facing contract policy validation asks, instead of importing
    Foundation-008's Pydantic result-schema classes directly (Foundation-009
    discovery refinement: keeps the two foundations independently
    consumable by the future Decision Engine, rather than policy validation
    coupling to core.evidence_result's implementation details).

    A concrete implementation (core.evidence_result.schema_catalog) is
    injected wherever policy validation runs; this module has no import of
    core.evidence_result at all -- Python's structural Protocol typing
    means the concrete class need not import this one either.
    """

    def is_known_evidence_type(self, evidence_type: str) -> bool:
        """True if `evidence_type` is a recognized Part III evidence type."""
        ...

    def supports_field(self, evidence_type: str, field: str) -> bool:
        """True if `field` is a valid reference for `evidence_type` -- either
        a field of its registered result-payload schema, or one of the
        universal EvidenceResult-level attributes (status/score/quality)
        that every evidence type carries regardless of payload shape."""
        ...
