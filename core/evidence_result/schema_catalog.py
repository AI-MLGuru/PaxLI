"""Concrete implementation of core.policy.schema_catalog.EvidenceSchemaCatalog
against this package's own SCHEMA_REGISTRY. No import of core.policy exists
here -- Python's structural Protocol typing means this class satisfies that
contract without inheriting from or referencing it, keeping the dependency
direction implicit rather than a hard import coupling in either direction.
"""

from core.evidence_result.enums import EvidenceResultType
from core.evidence_result.schemas import SCHEMA_REGISTRY

_UNIVERSAL_FIELDS = frozenset({"status", "score", "quality"})


class EvidenceResultSchemaCatalog:
    def is_known_evidence_type(self, evidence_type: str) -> bool:
        try:
            EvidenceResultType(evidence_type)
        except ValueError:
            return False
        return True

    def supports_field(self, evidence_type: str, field: str) -> bool:
        if field in _UNIVERSAL_FIELDS:
            return True
        try:
            result_type = EvidenceResultType(evidence_type)
        except ValueError:
            return False
        schema = SCHEMA_REGISTRY.get(result_type)
        if schema is None:
            return False
        return field in schema.model_fields
