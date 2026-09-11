"""SEC-7.6/7.12 authorization boundary for policy governance.

No router exists yet for policy management (Foundation-009 deliberately
excludes apps/ wiring, matching Foundation-008's precedent), so this proves
the boundary at the core.security.authorization level directly -- the same
mechanism apps/api/paxli_api/routers/management/credentials.py already
relies on for credential:manage, and where a future policy router would
plug in identically for policy:manage.
"""

from core.security.authorization import Permission, permissions_for_scope
from core.security.models import CredentialScope


def test_operational_scope_does_not_grant_policy_manage() -> None:
    permissions = permissions_for_scope(CredentialScope.OPERATIONAL)
    assert Permission.POLICY_MANAGE not in permissions


def test_administrative_scope_grants_policy_manage() -> None:
    permissions = permissions_for_scope(CredentialScope.ADMINISTRATIVE)
    assert Permission.POLICY_MANAGE in permissions
