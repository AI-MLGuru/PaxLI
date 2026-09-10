from typing import Protocol

from core.rate_limit.models import RateLimitDecision, RateLimitRule


class RateLimiterProtocol(Protocol):
    """Domain-facing contract for a single-dimension, atomic admission
    check. The concrete PostgreSQL implementation (Phase 2) owns its own
    session and commits independently of the caller's request transaction
    (Foundation-010 discovery correction: a consumed slot must remain
    consumed even if the request's later business logic fails and rolls
    back) -- nothing about that guarantee is visible or enforceable at this
    Protocol level, which is exactly why Phase 2's tests must prove it
    directly against real PostgreSQL rather than relying on this interface
    alone.

    Implementations MUST raise core.rate_limit.exceptions.
    RateLimiterUnavailableError for connectivity/timeout failures, and MUST
    NOT let any other exception type propagate from this method for such
    failures -- evaluate_admission() only ever treats that specific type as
    "limiter unavailable" eligible for fail_mode="open"."""

    async def check_and_consume(self, scope_key: str, rule: RateLimitRule) -> RateLimitDecision: ...
