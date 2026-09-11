"""Requirement traceability: Invariant 12.17 (12.76-12.80), 12.34/12.35 --
Invariant-12 remediation 3.

/v1/management/audit-events is the governance-event retrieval boundary:
POLICY_ACTIVATED, CREDENTIAL_*, and other non-session-scoped governed
events had no API retrieval path at all before this endpoint -- durable,
but previously only reachable by direct database access.
"""


def test_management_audit_events_returns_non_session_scoped_events(
    api_client, issued_credentials
) -> None:
    """CREDENTIAL_ISSUED has no session_id -- the existing
    /verification-sessions/{id}/audit-events endpoint could never surface
    it. The new management endpoint must."""
    headers = {"Authorization": issued_credentials["tenant_a_admin"]}
    api_client.post(
        "/v1/management/credentials",
        json={"name": "audit-retrieval-test", "scope": "OPERATIONAL"},
        headers=headers,
    )

    response = api_client.get("/v1/management/audit-events", headers=headers)
    assert response.status_code == 200
    event_types = {event["event_type"] for event in response.json()["data"]}
    assert "CREDENTIAL_ISSUED" in event_types


def test_management_audit_events_are_tenant_isolated(api_client, issued_credentials) -> None:
    api_client.post(
        "/v1/management/credentials",
        json={"name": "tenant-a-credential", "scope": "OPERATIONAL"},
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )

    tenant_b_response = api_client.get(
        "/v1/management/audit-events",
        headers={"Authorization": issued_credentials["tenant_b_operational"]},
    )
    assert tenant_b_response.status_code == 200
    tenant_b_actor_ids = {event["actor_id"] for event in tenant_b_response.json()["data"]}

    tenant_a_response = api_client.get(
        "/v1/management/audit-events",
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )
    tenant_a_credential_ids = {
        event["actor_id"]
        for event in tenant_a_response.json()["data"]
        if event["event_type"] == "CREDENTIAL_ISSUED"
    }
    # tenant-b's view must never contain a tenant-a actor/credential id
    assert not (tenant_a_credential_ids & tenant_b_actor_ids)


def test_management_audit_events_filters_by_event_type(api_client, issued_credentials) -> None:
    headers = {"Authorization": issued_credentials["tenant_a_admin"]}
    api_client.post(
        "/v1/management/credentials",
        json={"name": "filter-test", "scope": "OPERATIONAL"},
        headers=headers,
    )

    response = api_client.get(
        "/v1/management/audit-events",
        params={"event_type": "CREDENTIAL_ISSUED"},
        headers=headers,
    )
    assert response.status_code == 200
    events = response.json()["data"]
    assert len(events) >= 1
    assert all(event["event_type"] == "CREDENTIAL_ISSUED" for event in events)


def test_management_audit_events_requires_authentication(api_client) -> None:
    response = api_client.get("/v1/management/audit-events")
    assert response.status_code == 401
