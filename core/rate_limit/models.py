from dataclasses import dataclass

from core.rate_limit.enums import RateLimitScope


@dataclass(frozen=True)
class RateLimitRule:
    """One dimension's admission policy -- fixed-window (Foundation-010
    discovery decision #6: accepted, not "improved" into sliding-window
    behavior during implementation). Not persisted, not tenant-configurable
    (discovery Q10): rules are built once from static configuration."""

    scope: RateLimitScope
    limit: int
    window_seconds: int

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be at least 1")
        if self.window_seconds < 1:
            raise ValueError("window_seconds must be at least 1")


@dataclass(frozen=True)
class RateLimitDecision:
    """The result of one RateLimiterProtocol.check_and_consume() call for a
    single scope -- never itself a verification outcome (constitutional
    boundary: admission control, never REJECTED/INCONCLUSIVE)."""

    allowed: bool
    remaining: int
    retry_after_seconds: int
