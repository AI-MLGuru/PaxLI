from enum import StrEnum


class PolicyStatus(StrEnum):
    """Two-state lifecycle only (Foundation-009 discovery, approved).

    Part V §5.36 defers staged/shadow/simulation policy states for v1.0;
    nothing in the normative text requires an intermediate DRAFT/VALIDATED
    state between "submitted" and "active" -- a submission is either
    rejected before persistence (InvalidPolicyError, never stored) or
    persisted already ACTIVE. SUPERSEDED is a one-way transition from
    ACTIVE; no row ever transitions back to ACTIVE (Invariant 07 -- rollback
    creates a new version instead, see core.policy.service.rollback).
    """

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
