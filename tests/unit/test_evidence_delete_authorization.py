"""Invariant-06 remediation Phase 3: EVIDENCE_DELETE must remain
administrative-only, the same shape as test_policy_authorization.py proves
for POLICY_MANAGE."""

from core.security.authorization import Permission, permissions_for_scope
from core.security.models import CredentialScope


def test_operational_scope_does_not_grant_evidence_delete() -> None:
    permissions = permissions_for_scope(CredentialScope.OPERATIONAL)
    assert Permission.EVIDENCE_DELETE not in permissions


def test_administrative_scope_grants_evidence_delete() -> None:
    permissions = permissions_for_scope(CredentialScope.ADMINISTRATIVE)
    assert Permission.EVIDENCE_DELETE in permissions


def test_operational_scope_still_grants_evidence_read_and_submit() -> None:
    """EVIDENCE_DELETE must not be implied by EVIDENCE_READ, and adding it
    must not accidentally narrow the existing operational grants."""
    permissions = permissions_for_scope(CredentialScope.OPERATIONAL)
    assert Permission.EVIDENCE_READ in permissions
    assert Permission.EVIDENCE_SUBMIT in permissions
