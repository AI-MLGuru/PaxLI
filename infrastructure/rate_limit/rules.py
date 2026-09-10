from core.rate_limit.enums import RateLimitScope
from core.rate_limit.models import RateLimitRule


def authenticated_rules(*, limit: int, window_seconds: int) -> tuple[RateLimitRule, RateLimitRule]:
    """TENANT + CREDENTIAL scoped rules sharing one configured limit/window
    -- most-restrictive-wins evaluates both (Foundation-010 discovery
    decision #3). A general OPERATION-wide ceiling is deliberately not
    wired for v1: nothing in the approved scope requires it, and adding it
    would broaden the request-path change beyond what's necessary (Phase 3
    review guardrail)."""
    return (
        RateLimitRule(scope=RateLimitScope.TENANT, limit=limit, window_seconds=window_seconds),
        RateLimitRule(scope=RateLimitScope.CREDENTIAL, limit=limit, window_seconds=window_seconds),
    )


def pre_auth_rule(*, limit: int, window_seconds: int) -> RateLimitRule:
    return RateLimitRule(
        scope=RateLimitScope.NETWORK_SOURCE, limit=limit, window_seconds=window_seconds
    )
