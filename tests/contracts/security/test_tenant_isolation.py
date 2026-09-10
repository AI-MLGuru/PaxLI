"""Requirement traceability: SEC-7.5.*, PRV-11.11.*, PRV-11.19.*, Invariant 08."""


def _create_session(api_client, token: str) -> str:
    response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": token},
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


def test_cross_tenant_session_access_is_denied(api_client, issued_credentials) -> None:
    """SEC-7.5.5 / PRV-11.19.1: Tenant A must not access Tenant B's session."""
    session_id = _create_session(api_client, issued_credentials["tenant_b_operational"])

    response = api_client.get(
        f"/v1/verification-sessions/{session_id}",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert response.status_code == 404


def test_cross_tenant_evidence_access_is_denied(api_client, issued_credentials) -> None:
    """SEC-7.5.5 / PRV-11.19.2: Tenant A must not access Tenant B's evidence."""
    session_id = _create_session(api_client, issued_credentials["tenant_b_operational"])
    api_client.post(
        f"/v1/verification-sessions/{session_id}/selfie",
        files={"file": ("selfie.jpg", b"CANARY_SELFIE_BYTES", "image/jpeg")},
        headers={"Authorization": issued_credentials["tenant_b_operational"]},
    )

    response = api_client.get(
        f"/v1/verification-sessions/{session_id}/evidence",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert response.status_code == 404


def test_cross_tenant_audit_access_is_denied(api_client, issued_credentials) -> None:
    """SEC-7.5.5: Tenant A must not read Tenant B's audit trail."""
    session_id = _create_session(api_client, issued_credentials["tenant_b_operational"])

    response = api_client.get(
        f"/v1/verification-sessions/{session_id}/audit-events",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert response.status_code == 404


def test_forged_tenant_header_does_not_override_authenticated_tenant(
    api_client, issued_credentials
) -> None:
    """SEC-7.5.3 / PRV-11.11.2: a client-supplied tenant header MUST NOT override
    the authenticated context."""
    response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={
            "Authorization": issued_credentials["tenant_a_operational"],
            "X-Tenant-ID": "tenant-b",
        },
    )
    assert response.status_code == 201
    assert response.json()["data"]["tenant_id"] == "tenant-a"


def test_nonexistent_and_cross_tenant_session_return_identical_errors(
    api_client, issued_credentials
) -> None:
    """SEC-7.18.1 / SEC-7.4.6: unauthorized responses must not reveal whether the
    protected resource exists under another tenant."""
    real_other_tenant_session = _create_session(
        api_client, issued_credentials["tenant_b_operational"]
    )
    fake_session_id = "00000000-0000-0000-0000-000000000000"

    cross_tenant_response = api_client.get(
        f"/v1/verification-sessions/{real_other_tenant_session}",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    nonexistent_response = api_client.get(
        f"/v1/verification-sessions/{fake_session_id}",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )

    assert cross_tenant_response.status_code == nonexistent_response.status_code == 404
    assert cross_tenant_response.json() == nonexistent_response.json()
