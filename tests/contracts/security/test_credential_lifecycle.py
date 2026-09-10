"""Requirement traceability: SEC-7.8.*, SEC-7.9.*, SEC-7.10.*, SEC-7.11.*."""

from sqlalchemy import select

from infrastructure.database.models.audit_event import AuditEventRecord


async def _audit_event_types_for_tenant(session_factory, tenant_id: str) -> set[str]:
    async with session_factory() as session:
        result = await session.execute(
            select(AuditEventRecord).where(AuditEventRecord.tenant_id == tenant_id)
        )
        return {record.event_type for record in result.scalars().all()}


def test_issued_credential_authenticates(api_client, issued_credentials) -> None:
    """SEC-7.9.7 / SEC-7.10.2: a newly issued credential works immediately."""
    issue_response = api_client.post(
        "/v1/management/credentials",
        json={"name": "lifecycle-test", "scope": "OPERATIONAL"},
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )
    issued = issue_response.json()["data"]
    token = f"Bearer {issued['credential_id']}.{issued['secret']}"

    response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": token},
    )
    assert response.status_code == 201


def test_rotation_invalidates_old_secret_and_issues_new_one(api_client, issued_credentials) -> None:
    """SEC-7.11.2: rotation must not leave the historical secret usable."""
    issue_response = api_client.post(
        "/v1/management/credentials",
        json={"name": "rotation-test", "scope": "OPERATIONAL"},
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )
    issued = issue_response.json()["data"]
    old_token = f"Bearer {issued['credential_id']}.{issued['secret']}"

    rotate_response = api_client.post(
        f"/v1/management/credentials/{issued['credential_id']}/rotate",
        json={"name": "rotation-test-v2"},
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )
    assert rotate_response.status_code == 200
    rotated = rotate_response.json()["data"]
    new_token = f"Bearer {rotated['credential_id']}.{rotated['secret']}"

    old_secret_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": old_token},
    )
    assert old_secret_response.status_code == 401

    new_secret_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": new_token},
    )
    assert new_secret_response.status_code == 201


def test_revoked_credential_no_longer_authenticates(api_client, issued_credentials) -> None:
    """SEC-7.8.4 / SEC-7.11.1: revoked credentials must not authenticate."""
    issue_response = api_client.post(
        "/v1/management/credentials",
        json={"name": "revoke-test", "scope": "OPERATIONAL"},
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )
    issued = issue_response.json()["data"]
    token = f"Bearer {issued['credential_id']}.{issued['secret']}"

    revoke_response = api_client.post(
        f"/v1/management/credentials/{issued['credential_id']}/revoke",
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )
    assert revoke_response.status_code == 204

    response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": token},
    )
    assert response.status_code == 401


def test_credential_lifecycle_operations_are_auditable(
    api_client, issued_credentials, session_factory
) -> None:
    """SEC-7.8.7 / SEC-7.10.5 / SEC-7.11.5: issuance, rotation, and revocation
    must generate durable audit events."""
    import asyncio

    issue_response = api_client.post(
        "/v1/management/credentials",
        json={"name": "audited-credential", "scope": "OPERATIONAL"},
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )
    issued = issue_response.json()["data"]

    api_client.post(
        f"/v1/management/credentials/{issued['credential_id']}/rotate",
        json={"name": "audited-credential-v2"},
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )

    event_types = asyncio.run(_audit_event_types_for_tenant(session_factory, "tenant-a"))
    assert "CREDENTIAL_ISSUED" in event_types
    assert "CREDENTIAL_ROTATED" in event_types
