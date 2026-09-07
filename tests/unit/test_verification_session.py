from core.verification.enums import AssuranceLevel, VerificationStatus
from core.verification.models import VerificationSession


def test_session_defaults() -> None:
    session = VerificationSession(tenant_id="tenant-test")
    assert session.status == VerificationStatus.CREATED
    assert session.assurance_level == AssuranceLevel.STANDARD
    assert session.id is not None
