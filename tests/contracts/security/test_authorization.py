"""Requirement traceability: SEC-7.3.*, SEC-7.4.*, SEC-7.6.*, SEC-7.12.*."""


def test_missing_bearer_token_is_rejected(api_client) -> None:
    """SEC-7.3.1: protected operations require an authenticated principal."""
    response = api_client.post("/v1/verification-sessions", json={"assurance_level": "STANDARD"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"


def test_operational_credential_cannot_manage_credentials(api_client, issued_credentials) -> None:
    """SEC-7.12.1: operational credentials must not automatically possess
    administrative permissions."""
    response = api_client.post(
        "/v1/management/credentials",
        json={"name": "should-fail", "scope": "OPERATIONAL"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AUTHORIZATION_DENIED"


def test_administrative_credential_can_manage_credentials(api_client, issued_credentials) -> None:
    """SEC-7.6.4 positive path: administrative scope grants credential:manage."""
    response = api_client.post(
        "/v1/management/credentials",
        json={"name": "new-operational-key", "scope": "OPERATIONAL"},
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )
    assert response.status_code == 201
    assert response.json()["data"]["scope"] == "OPERATIONAL"
    assert response.json()["data"]["tenant_id"] == "tenant-a"


def test_malformed_bearer_token_is_generic_authentication_failure(api_client) -> None:
    """SEC-7.3.5 / SEC-7.18.1: failures must not distinguish malformed vs unknown."""
    response = api_client.get(
        "/v1/verification-sessions/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid credentials"
