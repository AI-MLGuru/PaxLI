import pytest

from core.rate_limit.enums import RateLimitScope
from core.rate_limit.evaluation import evaluate_admission
from core.rate_limit.exceptions import RateLimiterUnavailableError, RateLimitExceededError
from core.rate_limit.metrics import RateLimitMetrics
from core.rate_limit.models import RateLimitDecision, RateLimitRule


class FakeRateLimiter:
    """In-memory -- records every call it receives so tests can prove
    most-restrictive-wins short-circuits rather than checking every rule
    unconditionally."""

    def __init__(
        self,
        *,
        decisions: dict[str, RateLimitDecision] | None = None,
        raise_for: set[str] | None = None,
    ) -> None:
        self.decisions = decisions or {}
        self.calls: list[str] = []
        self.raise_for: set[str] = raise_for or set()

    async def check_and_consume(self, scope_key: str, rule: RateLimitRule) -> RateLimitDecision:
        self.calls.append(scope_key)
        if scope_key in self.raise_for:
            raise RateLimiterUnavailableError("simulated limiter infrastructure failure")
        return self.decisions.get(
            scope_key, RateLimitDecision(allowed=True, remaining=1, retry_after_seconds=0)
        )


def _rule(scope: RateLimitScope) -> RateLimitRule:
    return RateLimitRule(scope=scope, limit=10, window_seconds=60)


@pytest.mark.asyncio
async def test_all_rules_allowed_admits_the_request_and_checks_every_rule() -> None:
    limiter = FakeRateLimiter()
    metrics = RateLimitMetrics()
    rules_and_keys = [
        (_rule(RateLimitScope.TENANT), "tenant-key"),
        (_rule(RateLimitScope.CREDENTIAL), "credential-key"),
        (_rule(RateLimitScope.OPERATION), "operation-key"),
    ]

    await evaluate_admission(
        rules_and_keys=rules_and_keys, limiter=limiter, fail_mode="closed", metrics=metrics
    )

    assert limiter.calls == ["tenant-key", "credential-key", "operation-key"]
    assert metrics.snapshot().allowed == 3


@pytest.mark.asyncio
async def test_most_restrictive_wins_short_circuits_on_the_first_exhausted_scope() -> None:
    limiter = FakeRateLimiter(
        decisions={
            "credential-key": RateLimitDecision(allowed=False, remaining=0, retry_after_seconds=30)
        }
    )
    metrics = RateLimitMetrics()
    rules_and_keys = [
        (_rule(RateLimitScope.TENANT), "tenant-key"),
        (_rule(RateLimitScope.CREDENTIAL), "credential-key"),
        (_rule(RateLimitScope.OPERATION), "operation-key"),
    ]

    with pytest.raises(RateLimitExceededError) as exc_info:
        await evaluate_admission(
            rules_and_keys=rules_and_keys, limiter=limiter, fail_mode="closed", metrics=metrics
        )

    assert exc_info.value.limiting_scope == RateLimitScope.CREDENTIAL
    assert exc_info.value.retry_after_seconds == 30
    # the OPERATION scope was never checked -- the credential exhaustion
    # short-circuited the rest of the rule set
    assert limiter.calls == ["tenant-key", "credential-key"]
    assert metrics.snapshot().rejected == 1
    assert metrics.snapshot().allowed == 1  # only the tenant check passed before rejection


@pytest.mark.asyncio
async def test_fail_closed_raises_immediately_on_limiter_infrastructure_failure() -> None:
    limiter = FakeRateLimiter(raise_for={"credential-key"})
    metrics = RateLimitMetrics()
    rules_and_keys = [
        (_rule(RateLimitScope.TENANT), "tenant-key"),
        (_rule(RateLimitScope.CREDENTIAL), "credential-key"),
        (_rule(RateLimitScope.OPERATION), "operation-key"),
    ]

    with pytest.raises(RateLimitExceededError) as exc_info:
        await evaluate_admission(
            rules_and_keys=rules_and_keys, limiter=limiter, fail_mode="closed", metrics=metrics
        )

    assert exc_info.value.limiting_scope == RateLimitScope.CREDENTIAL
    assert limiter.calls == ["tenant-key", "credential-key"]
    assert metrics.snapshot().limiter_failures == 1


@pytest.mark.asyncio
async def test_fail_open_treats_a_limiter_failure_as_passed_and_continues() -> None:
    limiter = FakeRateLimiter(raise_for={"credential-key"})
    metrics = RateLimitMetrics()
    rules_and_keys = [
        (_rule(RateLimitScope.TENANT), "tenant-key"),
        (_rule(RateLimitScope.CREDENTIAL), "credential-key"),
        (_rule(RateLimitScope.OPERATION), "operation-key"),
    ]

    await evaluate_admission(
        rules_and_keys=rules_and_keys, limiter=limiter, fail_mode="open", metrics=metrics
    )

    # every rule was still checked, including the one after the failure
    assert limiter.calls == ["tenant-key", "credential-key", "operation-key"]
    assert metrics.snapshot().limiter_failures == 1
    assert metrics.snapshot().allowed == 2  # tenant + operation both genuinely allowed


@pytest.mark.asyncio
async def test_fail_open_never_suppresses_a_non_limiter_exception() -> None:
    """The no-bypass guardrail, tightened: evaluate_admission catches only
    RateLimiterUnavailableError, never bare Exception. A bug unrelated to
    limiter connectivity (a malformed scope key, a programming error --
    simulated here with a plain PermissionError from check_and_consume)
    must propagate loudly, even under fail_mode="open", rather than being
    silently absorbed as "limiter unavailable" and fail-opened past."""

    class RaisesAnUnrelatedError(FakeRateLimiter):
        async def check_and_consume(self, scope_key: str, rule: RateLimitRule) -> RateLimitDecision:
            raise PermissionError("not a RateLimiterUnavailableError -- must propagate untouched")

    limiter = RaisesAnUnrelatedError()
    metrics = RateLimitMetrics()
    rules_and_keys = [(_rule(RateLimitScope.TENANT), "any-key")]

    with pytest.raises(PermissionError):
        await evaluate_admission(
            rules_and_keys=rules_and_keys, limiter=limiter, fail_mode="open", metrics=metrics
        )
    # never counted as a limiter failure -- it was never caught at all
    assert metrics.snapshot().limiter_failures == 0
