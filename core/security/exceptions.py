class AuthenticationError(Exception):
    """Raised without revealing whether an identifier or secret was invalid."""


class AuthorizationError(Exception):
    """Raised when an authenticated principal lacks a required permission."""


class CredentialStateError(ValueError):
    """Raised when a credential lifecycle transition is invalid."""
