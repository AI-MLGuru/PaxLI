def test_create_get_cancel_session_round_trip(api_client, issued_credentials) -> None:
    headers = {"Authorization": issued_credentials["tenant_a_operational"]}

    create_response = api_client.post(
        "/v1/verification-sessions", json={"assurance_level": "STANDARD"}, headers=headers
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["data"]["id"]
    assert create_response.json()["data"]["tenant_id"] == "tenant-a"

    get_response = api_client.get(f"/v1/verification-sessions/{session_id}", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["data"]["id"] == session_id

    cancel_response = api_client.post(
        f"/v1/verification-sessions/{session_id}/cancel", headers=headers
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["data"]["status"] == "CANCELLED"

    audit_response = api_client.get(
        f"/v1/verification-sessions/{session_id}/audit-events", headers=headers
    )
    assert audit_response.status_code == 200
    event_types = [event["event_type"] for event in audit_response.json()["data"]]
    assert "SESSION_CREATED" in event_types
    assert "SESSION_CANCELLED" in event_types
