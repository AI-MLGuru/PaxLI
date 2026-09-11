class AuthenticationError(Exception):
    """Raised without revealing whether an identifier or secret was invalid.

    Carries whatever denial context is actually known (SEC-7.29.1) so the
    exception boundary can produce the required AUTHENTICATION_FAILED audit
    event without re-deriving it. Both fields are None when the request
    never resolved to a parseable credential identifier at all (malformed
    or missing bearer token), since there is nothing to attribute yet.
    """

    def __init__(self, *, credential_id: str | None = None, tenant_id: str | None = None) -> None:
        super().__init__("Invalid credentials")
        self.credential_id = credential_id
        self.tenant_id = tenant_id


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


class IdempotentReplayWithoutSecretError(Exception):
    """Raised when a retried issue/rotate request matches an
    idempotency_key already used successfully once. Unlike session/policy/
    evidence-result idempotency, credential issuance cannot simply return
    the original result on replay: the stored CredentialRecord holds only
    a one-way secret_verifier hash, and the raw secret is never persisted
    anywhere (SEC-7.9.9 -- credential secrets MUST NOT appear beyond
    authorized one-time issuance). Silently returning "success" without
    the secret would be worse than an error: the caller would have no way
    to tell they didn't receive it. This is a deliberate, explicit decision
    (Invariant-12 remediation), not an oversight."""

    def __init__(self, *, credential_id: str) -> None:
        super().__init__(
            "This credential was already issued under this idempotency key; "
            "the secret was shown once and cannot be retrieved again. "
            "Rotate the credential for a new secret if it was lost."
        )
        self.credential_id = credential_id
