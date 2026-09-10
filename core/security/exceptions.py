class AuthenticationError(Exception):
    """Raised without revealing whether an identifier or secret was invalid."""


class AuthorizationError(Exception):
    """Raised when an authenticated principal lacks a required permission.

    Carries the denial context (SEC-7.7.1) so the boundary that turns this
    into an HTTP response can also produce the required durable audit event
    (SEC-7.29.1 / Invariant 12.9.46) without re-deriving it.
    """

    def __init__(
        self,
        *,
        required_permission: str,
        tenant_id: str,
        actor_id: str,
        session_id: str | None = None,
    ) -> None:
        super().__init__(f"Missing required permission: {required_permission}")
        self.required_permission = required_permission
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.session_id = session_id


class CredentialStateError(ValueError):
    """Raised when a credential lifecycle transition is invalid."""
