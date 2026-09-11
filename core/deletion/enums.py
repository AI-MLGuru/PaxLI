from enum import StrEnum


class DeletionBasis(StrEnum):
    """Closed vocabulary (EVD-3.26.3: deletion MUST identify the applicable
    deletion basis). Shared between core.evidence and core.evidence_result
    -- the one piece of genuinely common deletion vocabulary between two
    packages that otherwise deliberately don't depend on each other
    (Foundation-008's stated boundary).

    Deliberately does NOT include a legal-hold-specific value: a legal hold
    is a more specialized records-management concept this codebase hasn't
    designed a subsystem for yet (Foundation review). Deliberately does NOT
    name a specific jurisdiction's statutory mechanism -- Averiq is
    Nigeria-first but not hard-coded to one jurisdiction (Part III §3.28),
    so LEGAL_REQUIREMENT stays general rather than encoding e.g. NDPA-
    specific terminology into the domain enum.
    """

    TENANT_REQUEST = "TENANT_REQUEST"
    DATA_SUBJECT_REQUEST = "DATA_SUBJECT_REQUEST"
    RETENTION_EXPIRY = "RETENTION_EXPIRY"
    LEGAL_REQUIREMENT = "LEGAL_REQUIREMENT"
    OTHER_AUTHORIZED_BASIS = "OTHER_AUTHORIZED_BASIS"
