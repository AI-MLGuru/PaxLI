from dataclasses import dataclass
from uuid import UUID

from core.security.credentials import CredentialService
from core.security.exceptions import AuthenticationError


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    credential_id: UUID
    tenant_id: str
    credential_name: str


async def authenticate_bearer(
    authorization: str | None, credential_service: CredentialService
) -> AuthenticatedPrincipal:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthenticationError("Invalid credentials")
    token = authorization.removeprefix("Bearer ")
    credential_id_text, separator, secret = token.partition(".")
    if not separator or not secret:
        raise AuthenticationError("Invalid credentials")
    try:
        credential_id = UUID(credential_id_text)
    except ValueError as exception:
        raise AuthenticationError("Invalid credentials") from exception
    credential = await credential_service.authenticate_by_id(
        credential_id=credential_id, secret=secret
    )
    return AuthenticatedPrincipal(credential.credential_id, credential.tenant_id, credential.name)
