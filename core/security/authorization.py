from enum import StrEnum

from core.security.exceptions import AuthorizationError
from core.security.models import CredentialScope


class Permission(StrEnum):
    VERIFICATION_CREATE = "verification:create"
    VERIFICATION_READ = "verification:read"
    VERIFICATION_CANCEL = "verification:cancel"
    EVIDENCE_SUBMIT = "evidence:submit"
    EVIDENCE_READ = "evidence:read"
    AUDIT_READ = "audit:read"
    CREDENTIAL_MANAGE = "credential:manage"


_OPERATIONAL_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.VERIFICATION_CREATE,
        Permission.VERIFICATION_READ,
        Permission.VERIFICATION_CANCEL,
        Permission.EVIDENCE_SUBMIT,
        Permission.EVIDENCE_READ,
        Permission.AUDIT_READ,
    }
)

_ADMINISTRATIVE_ONLY_PERMISSIONS: frozenset[Permission] = frozenset({Permission.CREDENTIAL_MANAGE})


def permissions_for_scope(scope: CredentialScope) -> frozenset[Permission]:
    if scope == CredentialScope.ADMINISTRATIVE:
        return _OPERATIONAL_PERMISSIONS | _ADMINISTRATIVE_ONLY_PERMISSIONS
    return _OPERATIONAL_PERMISSIONS


def require_permission(granted: frozenset[Permission], required: Permission) -> None:
    """Authorization gate: MUST be called before the protected side effect (SEC-7.4.2)."""
    if required not in granted:
        raise AuthorizationError(f"Missing required permission: {required.value}")
