class DecisionAlreadyExistsError(RuntimeError):
    """Raised when a concurrent evaluation attempt already produced and
    durably persisted a decision for this (tenant_id, session_id) -- the
    database's UNIQUE(tenant_id, session_id) constraint is the sole final
    authority (DE-003 §14 step 3), never an application-level
    check-then-insert. The losing attempt is not a caller error:
    DecisionPersistenceService.persist() catches this internally and
    returns the winning row as success -- a session gets evaluated to a
    durable decision exactly once, ever, and every concurrent attempt
    observes that same outcome."""
