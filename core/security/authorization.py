from enum import StrEnum
from typing import TYPE_CHECKING

from core.security.exceptions import AuthorizationError
from core.security.models import CredentialScope

if TYPE_CHECKING:
    from core.security.authentication import AuthenticatedPrincipal


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


def require_permission(
    principal: "AuthenticatedPrincipal", required: Permission, *, session_id: str | None = None
) -> None:
    """Authorization gate: MUST be called before the protected side effect (SEC-7.4.2).

    Raises with enough context for the caller to produce the required
    AUTHORIZATION_DENIED audit event (SEC-7.29.1) without a second lookup.
    """
    if required not in principal.permissions:
        raise AuthorizationError(
            required_permission=required.value,
            tenant_id=principal.tenant_id,
            actor_id=str(principal.credential_id),
            session_id=session_id,
        )
