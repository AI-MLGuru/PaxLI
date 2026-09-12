from datetime import UTC, datetime, timedelta

from core.verification.enums import AssuranceLevel, VerificationStatus
from core.verification.models import VerificationSession


def test_session_defaults() -> None:
    session = VerificationSession(tenant_id="tenant-test")
    assert session.status == VerificationStatus.CREATED
    assert session.assurance_level == AssuranceLevel.STANDARD
    assert session.id is not None


def _session_expiring_at(expires_at: datetime) -> VerificationSession:
    return VerificationSession(
        tenant_id="tenant-test",
        status=VerificationStatus.CREATED,
        assurance_level=AssuranceLevel.STANDARD,
        created_at=expires_at - timedelta(hours=1),
        expires_at=expires_at,
    )


def test_is_past_expiry_at_the_exact_boundary_instant() -> None:
    """WF-HV-008 / WF-006 Finding H: the literal boundary instant itself,
    not "one minute before" or "one minute after" -- is_past_expiry()
    uses an inclusive `now >= expires_at` comparison, so the exact
    instant of equality must count as expired, never fall through to an
    undefined "not yet" edge. A microsecond-resolution `now` is passed
    explicitly (the same `now` parameter is_past_expiry()/expire_if_needed()
    already accept for exactly this kind of precise testing), so this
    isn't approximated by wall-clock timing at all."""
    boundary = datetime(2026, 1, 1, 12, 0, 0, 0, tzinfo=UTC)
    session = _session_expiring_at(boundary)

    assert session.is_past_expiry(now=boundary) is True


def test_is_past_expiry_one_microsecond_before_the_boundary() -> None:
    boundary = datetime(2026, 1, 1, 12, 0, 0, 0, tzinfo=UTC)
    session = _session_expiring_at(boundary)

    assert session.is_past_expiry(now=boundary - timedelta(microseconds=1)) is False


def test_is_past_expiry_one_microsecond_after_the_boundary() -> None:
    boundary = datetime(2026, 1, 1, 12, 0, 0, 0, tzinfo=UTC)
    session = _session_expiring_at(boundary)

    assert session.is_past_expiry(now=boundary + timedelta(microseconds=1)) is True


def test_expire_if_needed_transitions_at_the_exact_boundary_instant() -> None:
    """The same boundary, exercised through the actual transition method
    (not just the read-only predicate) -- proves the CREATED->EXPIRED
    transition itself, not merely the comparison it's gated on, treats
    the exact instant as expired."""
    boundary = datetime(2026, 1, 1, 12, 0, 0, 0, tzinfo=UTC)
    session = _session_expiring_at(boundary)

    assert session.expire_if_needed(now=boundary) is True
    assert session.status is VerificationStatus.EXPIRED


def test_expire_if_needed_does_not_transition_one_microsecond_before_the_boundary() -> None:
    boundary = datetime(2026, 1, 1, 12, 0, 0, 0, tzinfo=UTC)
    session = _session_expiring_at(boundary)

    assert session.expire_if_needed(now=boundary - timedelta(microseconds=1)) is False
    assert session.status is VerificationStatus.CREATED
