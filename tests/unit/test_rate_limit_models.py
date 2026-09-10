import pytest

from core.rate_limit.enums import RateLimitScope
from core.rate_limit.models import RateLimitDecision, RateLimitRule


def test_rate_limit_rule_constructs_with_valid_values() -> None:
    rule = RateLimitRule(scope=RateLimitScope.TENANT, limit=60, window_seconds=60)
    assert rule.limit == 60
    assert rule.window_seconds == 60


@pytest.mark.parametrize("limit", [0, -1])
def test_rate_limit_rule_rejects_non_positive_limit(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        RateLimitRule(scope=RateLimitScope.TENANT, limit=limit, window_seconds=60)


@pytest.mark.parametrize("window_seconds", [0, -5])
def test_rate_limit_rule_rejects_non_positive_window(window_seconds: int) -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        RateLimitRule(scope=RateLimitScope.TENANT, limit=10, window_seconds=window_seconds)


def test_rate_limit_decision_is_a_plain_immutable_value() -> None:
    decision = RateLimitDecision(allowed=True, remaining=5, retry_after_seconds=0)
    assert decision.allowed is True
    with pytest.raises(AttributeError):
        decision.allowed = False  # type: ignore[misc]
