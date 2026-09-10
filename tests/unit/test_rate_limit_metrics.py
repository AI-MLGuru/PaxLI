from core.rate_limit.metrics import RateLimitMetrics


def test_snapshot_starts_at_zero() -> None:
    metrics = RateLimitMetrics()
    snapshot = metrics.snapshot()
    assert (snapshot.checks, snapshot.allowed, snapshot.rejected, snapshot.limiter_failures) == (
        0,
        0,
        0,
        0,
    )


def test_record_allowed_increments_checks_and_allowed() -> None:
    metrics = RateLimitMetrics()
    metrics.record_allowed()
    metrics.record_allowed()
    snapshot = metrics.snapshot()
    assert snapshot.checks == 2
    assert snapshot.allowed == 2
    assert snapshot.rejected == 0


def test_record_rejected_increments_checks_and_rejected() -> None:
    metrics = RateLimitMetrics()
    metrics.record_rejected()
    snapshot = metrics.snapshot()
    assert snapshot.checks == 1
    assert snapshot.rejected == 1
    assert snapshot.allowed == 0


def test_record_limiter_failure_does_not_affect_checks() -> None:
    """A limiter-unavailable event is tracked separately from the
    allowed/rejected admission-decision counters -- it isn't itself an
    admission decision."""
    metrics = RateLimitMetrics()
    metrics.record_limiter_failure()
    snapshot = metrics.snapshot()
    assert snapshot.limiter_failures == 1
    assert snapshot.checks == 0
