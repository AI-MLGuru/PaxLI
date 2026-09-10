from core.rate_limit.enums import RateLimitScope

# "|" is used as the field separator rather than ":" -- credential/network
# identifiers are opaque strings here (never parsed back out of the key),
# so collision-proofing beyond "don't let two different scopes produce the
# same key" isn't a security boundary, just a correctness nicety. The scope
# name is always embedded first so a TENANT key can never collide with a
# CREDENTIAL key even if the underlying identifier strings happened to match.


def build_scope_key(
    scope: RateLimitScope,
    operation: str,
    *,
    tenant_id: str | None = None,
    credential_id: str | None = None,
    network_source_key: str | None = None,
) -> str:
    """Deterministic composite key for one RateLimitRule's counter.
    Foundation-010 discovery Q5: tenant/credential/operation are the
    bounded-cardinality v1 dimensions; network_source_key is pre-hashed
    (HMAC, Phase 2/3) by the caller before it ever reaches this function --
    this module never sees or handles a raw IP address."""
    if scope is RateLimitScope.TENANT:
        if not tenant_id:
            raise ValueError("tenant_id is required for RateLimitScope.TENANT")
        return f"TENANT|{operation}|{tenant_id}"
    if scope is RateLimitScope.CREDENTIAL:
        if not credential_id:
            raise ValueError("credential_id is required for RateLimitScope.CREDENTIAL")
        return f"CREDENTIAL|{operation}|{credential_id}"
    if scope is RateLimitScope.OPERATION:
        return f"OPERATION|{operation}"
    if scope is RateLimitScope.NETWORK_SOURCE:
        if not network_source_key:
            raise ValueError("network_source_key is required for RateLimitScope.NETWORK_SOURCE")
        return f"NETWORK_SOURCE|{operation}|{network_source_key}"
    raise TypeError(f"unknown RateLimitScope: {scope!r}")
