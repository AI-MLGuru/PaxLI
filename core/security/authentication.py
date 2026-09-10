from dataclasses import dataclass
from uuid import UUID

from core.security.authorization import Permission, permissions_for_scope
from core.security.credentials import CredentialService
from core.security.exceptions import AuthenticationError
from core.security.models import CredentialScope


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    credential_id: UUID
    tenant_id: str
    credential_name: str
    scope: CredentialScope
    permissions: frozenset[Permission]


async def authenticate_bearer(
    authorization: str | None, credential_service: CredentialService
) -> AuthenticatedPrincipal:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthenticationError()
    token = authorization.removeprefix("Bearer ")
    credential_id_text, separator, secret = token.partition(".")
    if not separator or not secret:
        raise AuthenticationError()
    try:
        credential_id = UUID(credential_id_text)
    except ValueError as exception:
        raise AuthenticationError() from exception
    credential = await credential_service.authenticate_by_id(
        credential_id=credential_id, secret=secret
    )
    return AuthenticatedPrincipal(
        credential.credential_id,
        credential.tenant_id,
        credential.name,
        credential.scope,
        permissions_for_scope(credential.scope),
    )
