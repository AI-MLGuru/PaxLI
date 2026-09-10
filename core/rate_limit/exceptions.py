from core.rate_limit.enums import RateLimitScope


class RateLimiterUnavailableError(RuntimeError):
    """The only exception type evaluate_admission() treats as a limiter
    infrastructure failure eligible for fail_mode="open" (Foundation-010
    discovery decision #2/guardrail #3). A concrete RateLimiterProtocol
    implementation MUST raise this specific type for connectivity/timeout
    failures -- never let evaluate_admission catch bare Exception, or an
    unrelated bug (e.g. a malformed scope key) would be silently treated as
    "limiter unavailable" and fail-opened past on operational endpoints."""


class RateLimitExceededError(RuntimeError):
    """Raised by evaluate_admission() -- either a genuinely exhausted
    allowance, or (fail_mode="closed") a limiter infrastructure failure on a
    security-critical endpoint class. Carries enough for the API layer's
    429/Retry-After response without a second lookup, mirroring
    AuthenticationError/AuthorizationError's existing shape.

    This is purely an admission-control signal. Nothing in core.rate_limit
    imports core.verification.enums.VerificationStatus or
    core.evidence_result.enums.EvidenceResultStatus, and nothing translates
    this exception into either -- a rate-limit rejection can never become a
    verification outcome (API-6.23.6 / SEC-7.32.5)."""

    def __init__(self, *, retry_after_seconds: int, limiting_scope: RateLimitScope) -> None:
        self.retry_after_seconds = retry_after_seconds
        self.limiting_scope = limiting_scope
        super().__init__(
            f"rate limit exceeded for scope={limiting_scope.value}, "
            f"retry_after_seconds={retry_after_seconds}"
        )
