class InvalidPolicyError(ValueError):
    """Raised when a policy submission fails schema, semantic, or complexity
    validation (DEC-5.9/5.10, Invariant 07 §7.7/7.8). Rejected before
    anything is persisted -- there is no draft state for an invalid policy
    (Foundation-009 discovery, question 1)."""


class PolicyActivationConflictError(RuntimeError):
    """Raised when two concurrent activation attempts race for the same
    (tenant_id, assurance_level) applicability slot. The database's partial
    unique index is the sole final authority (Foundation-009 discovery,
    question 8); this error is a translation of that constraint violation,
    never a substitute for it via an application-level check-then-insert."""


class PolicyVersionNotFoundError(LookupError):
    """Raised by rollback() when the requested (policy_id, version) does not
    exist for the tenant -- there is nothing valid to roll back to."""


class NoActivePolicyError(LookupError):
    """Raised by VerificationSessionService.create() (DE-002/DE-003 §1
    early policy binding) when no ACTIVE policy exists for the requested
    (tenant_id, assurance_level). A creation-time failure, not a Decision
    Engine INCONCLUSIVE -- there is no session yet to attach a decision
    outcome to, and DE-003 §8 deliberately keeps this out of
    EngineReasonCode for exactly that reason: under early binding, no
    decision-bearing session can ever exist without a resolved policy, so
    this can only ever be a session-creation-time API error."""
