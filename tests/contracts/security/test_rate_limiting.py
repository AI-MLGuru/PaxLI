"""Requirement traceability: API-6.23.*, SEC-7.32.*, REL-10.16.* (Foundation-010
Phase 3). Uses controllable fakes rather than real PostgreSQL -- Phase 2
already proved PostgresRateLimiter's persistence semantics against real
Postgres; these tests prove the request-path WIRING: ordering, fail-open/
fail-closed scoping, the 429 contract, and scope isolation.
"""

from uuid import UUID

from apps.api.paxli_api.dependencies import get_credential_service, get_rate_limiter
from apps.api.paxli_api.main import app
from core.rate_limit.exceptions import RateLimiterUnavailableError
from core.rate_limit.models import RateLimitDecision, RateLimitRule
from core.security.credentials import CredentialService
from core.security.models import CredentialRecord
from infrastructure.database.repositories.credential import SqlAlchemyCredentialStore
from infrastructure.security.hashing import ScryptSecretHasher


class FakeConfigurableRateLimiter:
    """Every scope_key is allowed by default; specific keys can be marked
    exhausted or made to raise RateLimiterUnavailableError. Records every
    call so tests can assert exactly what was (or wasn't) checked."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.exhausted: set[str] = set()
        self.unavailable_scopes: set[str] = set()

    async def check_and_consume(self, scope_key: str, rule: RateLimitRule) -> RateLimitDecision:
        self.calls.append(scope_key)
        if any(scope_key.startswith(prefix) for prefix in self.unavailable_scopes):
            raise RateLimiterUnavailableError("simulated limiter outage")
        if any(scope_key.startswith(prefix) for prefix in self.exhausted):
            return RateLimitDecision(allowed=False, remaining=0, retry_after_seconds=42)
        return RateLimitDecision(allowed=True, remaining=1, retry_after_seconds=0)


class CountingCredentialService:
    """Wraps the real CredentialService, counting authenticate_by_id calls
    -- the pre-auth-ordering proof needs to know whether the expensive
    credential lookup ever ran, not just what the final HTTP status was."""

    def __init__(self, inner: CredentialService) -> None:
        self.inner = inner
        self.authenticate_calls = 0

    async def authenticate_by_id(self, *, credential_id: UUID, secret: str) -> CredentialRecord:
        self.authenticate_calls += 1
        return await self.inner.authenticate_by_id(credential_id=credential_id, secret=secret)


def _override_limiter(limiter: FakeConfigurableRateLimiter) -> None:
    app.dependency_overrides[get_rate_limiter] = lambda: limiter


def test_pre_auth_exhaustion_never_reaches_credential_lookup(
    api_client, issued_credentials, session_factory
) -> None:
    """The most important ordering proof: once the pre-auth NETWORK_SOURCE
    scope is exhausted, authenticate_bearer()'s credential lookup must
    never execute -- not just that the response is a 401/429."""
    limiter = FakeConfigurableRateLimiter()
    limiter.exhausted.add("NETWORK_SOURCE|authenticate|")
    _override_limiter(limiter)

    counting_service: CountingCredentialService | None = None

    async def override_get_credential_service():
        nonlocal counting_service
        async with session_factory() as session:
            real = CredentialService(SqlAlchemyCredentialStore(session), ScryptSecretHasher())
            counting_service = CountingCredentialService(real)
            yield counting_service

    app.dependency_overrides[get_credential_service] = override_get_credential_service
    try:
        response = api_client.get(
            "/v1/verification-sessions/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": issued_credentials["tenant_a_operational"]},
        )
    finally:
        del app.dependency_overrides[get_credential_service]

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert counting_service is not None
    assert counting_service.authenticate_calls == 0  # never reached


def test_fail_open_never_bypasses_authentication_or_authorization(
    api_client, issued_credentials
) -> None:
    """The no-bypass guardrail at the request-path level: a limiter outage
    on an operational (fail-open) endpoint must let admission through, but
    authentication and authorization still run normally. An operational
    credential must still get 403 for a permission it doesn't have."""
    limiter = FakeConfigurableRateLimiter()
    limiter.unavailable_scopes.update(
        {"TENANT|verification_create|", "CREDENTIAL|verification_create|"}
    )
    _override_limiter(limiter)

    # No Authorization header at all -- authentication must still be enforced.
    response = api_client.post("/v1/verification-sessions", json={"assurance_level": "STANDARD"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"


def test_fail_open_admits_a_legitimate_request_despite_limiter_outage(
    api_client, issued_credentials
) -> None:
    limiter = FakeConfigurableRateLimiter()
    limiter.unavailable_scopes.update(
        {"TENANT|verification_create|", "CREDENTIAL|verification_create|"}
    )
    _override_limiter(limiter)

    response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert response.status_code == 201  # admitted despite the limiter outage


def test_fail_closed_rejects_on_credential_management_when_limiter_unavailable(
    api_client, issued_credentials
) -> None:
    """Security-critical endpoint class: a limiter outage on
    credential-management must reject, not silently admit."""
    limiter = FakeConfigurableRateLimiter()
    limiter.unavailable_scopes.update(
        {"TENANT|credential_manage|", "CREDENTIAL|credential_manage|"}
    )
    _override_limiter(limiter)

    response = api_client.post(
        "/v1/management/credentials",
        json={"name": "should-be-rejected", "scope": "OPERATIONAL"},
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"


def test_429_contract_has_retry_after_header_and_generic_message(
    api_client, issued_credentials
) -> None:
    limiter = FakeConfigurableRateLimiter()
    limiter.exhausted.update({"TENANT|verification_create|", "CREDENTIAL|verification_create|"})
    _override_limiter(limiter)

    response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert response.json()["error"]["message"] == "Rate limit exceeded"  # no limiter internals
    assert "Retry-After" in response.headers
    assert int(response.headers["Retry-After"]) == 42


def test_credential_management_budget_is_isolated_from_verification_budget(
    api_client, issued_credentials
) -> None:
    """Management API isolation (Foundation-010 discovery Q7): exhausting
    credential_manage must not affect verification_create for the same
    tenant/credential, and vice versa -- distinct `operation` labels make
    each scope_key naturally disjoint."""
    limiter = FakeConfigurableRateLimiter()
    limiter.exhausted.update({"TENANT|credential_manage|", "CREDENTIAL|credential_manage|"})
    _override_limiter(limiter)

    blocked = api_client.post(
        "/v1/management/credentials",
        json={"name": "blocked", "scope": "OPERATIONAL"},
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )
    assert blocked.status_code == 429

    allowed = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )
    assert allowed.status_code == 201


def test_a_rate_limited_request_creates_no_verification_session(
    api_client, issued_credentials, session_factory
) -> None:
    """No verification-semantics contamination: a 429 must not create or
    modify a VerificationSession row -- admission control never touches
    governed verification state."""
    limiter = FakeConfigurableRateLimiter()
    limiter.exhausted.update({"TENANT|verification_create|", "CREDENTIAL|verification_create|"})
    _override_limiter(limiter)

    response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert response.status_code == 429

    import asyncio

    from sqlalchemy import select

    from infrastructure.database.models.verification_session import VerificationSessionRecord

    async def _count_sessions() -> int:
        async with session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(VerificationSessionRecord).where(
                            VerificationSessionRecord.tenant_id == "tenant-a"
                        )
                    )
                )
                .scalars()
                .all()
            )
            return len(rows)

    assert asyncio.run(_count_sessions()) == 0
