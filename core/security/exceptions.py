class AuthenticationError(Exception):
    """Raised without revealing whether an identifier or secret was invalid."""


class CredentialStateError(ValueError):
    """Raised when a credential lifecycle transition is invalid."""
