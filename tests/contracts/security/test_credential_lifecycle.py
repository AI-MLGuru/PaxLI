"""Requirement traceability: SEC-7.8.*, SEC-7.9.*, SEC-7.10.*, SEC-7.11.*."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from infrastructure.database.models.audit_event import AuditEventRecord
from infrastructure.database.models.credential import CredentialRecordModel


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


def test_repeated_issue_with_same_idempotency_key_errors_rather_than_fakes_success(
    api_client, issued_credentials
) -> None:
    """Invariant-12 remediation, explicit decision: since the raw secret is
    never recoverable from the stored hash, a same-key replay of issuance
    must be a clear error -- never a 200/201 that silently omits the
    secret the caller actually needs."""
    headers = {
        "Authorization": issued_credentials["tenant_a_admin"],
        "Idempotency-Key": "same-issue-key",
    }
    first = api_client.post(
        "/v1/management/credentials",
        json={"name": "idem-issue-test", "scope": "OPERATIONAL"},
        headers=headers,
    )
    assert first.status_code == 201

    second = api_client.post(
        "/v1/management/credentials",
        json={"name": "idem-issue-test", "scope": "OPERATIONAL"},
        headers=headers,
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENT_REPLAY_SECRET_UNAVAILABLE"
    assert "cannot be retrieved again" in second.json()["error"]["message"]


def test_repeated_rotate_with_same_idempotency_key_errors_rather_than_fakes_success(
    api_client, issued_credentials
) -> None:
    headers = {"Authorization": issued_credentials["tenant_a_admin"]}
    issue_response = api_client.post(
        "/v1/management/credentials",
        json={"name": "idem-rotate-test", "scope": "OPERATIONAL"},
        headers=headers,
    )
    credential_id = issue_response.json()["data"]["credential_id"]

    rotate_headers = {**headers, "Idempotency-Key": "same-rotate-key"}
    first = api_client.post(
        f"/v1/management/credentials/{credential_id}/rotate",
        json={"name": "idem-rotate-test-v2"},
        headers=rotate_headers,
    )
    assert first.status_code == 200
    new_credential_id = first.json()["data"]["credential_id"]

    second = api_client.post(
        f"/v1/management/credentials/{new_credential_id}/rotate",
        json={"name": "idem-rotate-test-v3"},
        headers=rotate_headers,
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENT_REPLAY_SECRET_UNAVAILABLE"


def test_same_raw_idempotency_key_does_not_collide_between_issue_and_rotate(
    api_client, issued_credentials
) -> None:
    """The composed key must be operation-scoped: reusing the same raw
    Idempotency-Key value for an issue and, separately, a rotate must not
    have the second call mistaken for a replay of the first (Invariant-12
    remediation review)."""
    headers = {"Authorization": issued_credentials["tenant_a_admin"]}
    issue_response = api_client.post(
        "/v1/management/credentials",
        json={"name": "shared-key-test", "scope": "OPERATIONAL"},
        headers={**headers, "Idempotency-Key": "shared-raw-key"},
    )
    assert issue_response.status_code == 201
    credential_id = issue_response.json()["data"]["credential_id"]

    rotate_response = api_client.post(
        f"/v1/management/credentials/{credential_id}/rotate",
        json={"name": "shared-key-test-v2"},
        headers={**headers, "Idempotency-Key": "shared-raw-key"},
    )
    assert rotate_response.status_code == 200  # not treated as a replay of the issue


def test_revoking_an_expired_credential_returns_409_and_audits_the_failure(
    api_client, issued_credentials, session_factory
) -> None:
    """Invariant-12 remediation 2: a material, externally initiated
    credential-management failure (revoking an already-expired credential)
    is a governance-relevant action, and must produce a durable
    CREDENTIAL_OPERATION_FAILED audit event via the global exception
    handler's independent transaction -- not silently fail or 500."""
    import asyncio

    headers = {"Authorization": issued_credentials["tenant_a_admin"]}
    issue_response = api_client.post(
        "/v1/management/credentials",
        json={"name": "will-expire", "scope": "OPERATIONAL"},
        headers=headers,
    )
    credential_id = issue_response.json()["data"]["credential_id"]

    async def _force_expiry() -> None:
        async with session_factory() as session:
            record = await session.get(CredentialRecordModel, credential_id)
            record.expires_at = datetime.now(UTC) - timedelta(days=1)
            await session.commit()

    asyncio.run(_force_expiry())

    revoke_response = api_client.post(
        f"/v1/management/credentials/{credential_id}/revoke", headers=headers
    )
    assert revoke_response.status_code == 409
    assert revoke_response.json()["error"]["code"] == "CREDENTIAL_STATE_CONFLICT"

    async def _failure_events() -> list[str]:
        async with session_factory() as session:
            result = await session.execute(
                select(AuditEventRecord).where(
                    AuditEventRecord.tenant_id == "tenant-a",
                    AuditEventRecord.event_type == "CREDENTIAL_OPERATION_FAILED",
                )
            )
            return [record.actor_id for record in result.scalars().all()]

    actor_ids = asyncio.run(_failure_events())
    assert len(actor_ids) == 1
    assert actor_ids[0] is not None
