import logging
from collections.abc import Sequence
from typing import Literal

from core.rate_limit.exceptions import RateLimiterUnavailableError, RateLimitExceededError
from core.rate_limit.limiter import RateLimiterProtocol
from core.rate_limit.metrics import RateLimitMetrics
from core.rate_limit.models import RateLimitRule

logger = logging.getLogger(__name__)

FailMode = Literal["open", "closed"]


async def evaluate_admission(
    *,
    rules_and_keys: Sequence[tuple[RateLimitRule, str]],
    limiter: RateLimiterProtocol,
    fail_mode: FailMode,
    metrics: RateLimitMetrics,
) -> None:
    """Most-restrictive-wins (Foundation-010 discovery decision #3): checks
    every configured (rule, scope_key) pair in order; the first exhausted
    scope raises RateLimitExceededError immediately. No weighting, no
    priority, no conflict resolution -- deliberately primitive.

    The only thing this function ever catches is a RateLimiterUnavailableError
    from limiter.check_and_consume() -- deliberately not bare Exception, so
    an unrelated bug (a malformed scope key, a programming error) propagates
    loudly instead of being silently absorbed as "limiter unavailable" and
    fail-opened past. It has no knowledge of authentication or authorization
    and calls neither -- fail_mode="open" can therefore only ever mean
    "treat this one exhausted-or-unreachable rule as passed," never "skip
    the rest of the request pipeline." That is a structural guarantee, not
    just a documented intention: there is no broader try/except anywhere in
    or around this function for authentication/authorization to be caught
    by.
    """
    for rule, scope_key in rules_and_keys:
        try:
            decision = await limiter.check_and_consume(scope_key, rule)
        except RateLimiterUnavailableError:
            logger.warning(
                "rate_limit_check_failed",
                extra={"scope": rule.scope.value, "fail_mode": fail_mode},
            )
            metrics.record_limiter_failure()
            if fail_mode == "closed":
                raise RateLimitExceededError(
                    retry_after_seconds=rule.window_seconds, limiting_scope=rule.scope
                ) from None
            continue
        if not decision.allowed:
            metrics.record_rejected()
            raise RateLimitExceededError(
                retry_after_seconds=decision.retry_after_seconds, limiting_scope=rule.scope
            )
        metrics.record_allowed()
