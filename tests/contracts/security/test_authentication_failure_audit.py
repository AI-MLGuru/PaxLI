"""Requirement traceability: SEC-7.29.1, Invariant 12.9, Invariant 12.14/12.15.

Mirrors test_authorization_denial_audit.py: a failed authentication attempt
is security-relevant and must leave a durable audit event, with the same
fail-closed behavior if that audit event itself cannot be recorded.
"""

from uuid import uuid4

from sqlalchemy import select

from apps.api.averiq_api.main import app
from core.audit.enums import UNATTRIBUTED_TENANT_ID
from infrastructure.database.models.audit_event import AuditEventRecord


async def _authentication_failed_events(session_factory, tenant_id: str) -> list[AuditEventRecord]:
    async with session_factory() as session:
        result = await session.execute(
            select(AuditEventRecord).where(
                AuditEventRecord.tenant_id == tenant_id,
                AuditEventRecord.event_type == "AUTHENTICATION_FAILED",
            )
        )
        return list(result.scalars().all())


def test_wrong_secret_for_existing_credential_is_audited_against_its_tenant(
    api_client, issued_credentials, session_factory
) -> None:
    import asyncio

    credential_id = issued_credentials["tenant_a_operational"].split(" ")[1].split(".")[0]
    response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": f"Bearer {credential_id}.wrong-secret"},
    )
    assert response.status_code == 401

    events = asyncio.run(_authentication_failed_events(session_factory, "tenant-a"))
    assert len(events) == 1
    assert events[0].actor_id == credential_id
    assert events[0].status == "FAILURE"


def test_unknown_credential_id_is_audited_under_the_unattributed_sentinel(
    api_client, session_factory
) -> None:
    import asyncio

    random_credential_id = str(uuid4())
    response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": f"Bearer {random_credential_id}.some-secret"},
    )
    assert response.status_code == 401

    events = asyncio.run(_authentication_failed_events(session_factory, UNATTRIBUTED_TENANT_ID))
    assert len(events) == 1
    assert events[0].actor_id == random_credential_id


def test_malformed_bearer_token_is_still_audited_without_a_credential_id(
    api_client, session_factory
) -> None:
    import asyncio

    response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": "Bearer not-a-valid-token-format"},
    )
    assert response.status_code == 401

    events = asyncio.run(_authentication_failed_events(session_factory, UNATTRIBUTED_TENANT_ID))
    assert len(events) == 1
    assert events[0].actor_id is None


def test_authentication_failure_audit_failure_returns_503_not_plain_401(
    api_client, issued_credentials
) -> None:
    class BrokenSessionFactory:
        def __call__(self):
            raise RuntimeError("simulated audit database outage")

    original = app.state.db_session_factory
    app.state.db_session_factory = BrokenSessionFactory()
    try:
        response = api_client.post(
            "/v1/verification-sessions",
            json={"assurance_level": "STANDARD"},
            headers={"Authorization": "Bearer not-a-valid-token-format"},
        )
    finally:
        app.state.db_session_factory = original

    assert response.status_code in {500, 503}


def test_secret_never_appears_in_the_audit_event(
    api_client, issued_credentials, session_factory
) -> None:
    import asyncio
    import json

    credential_id = issued_credentials["tenant_a_operational"].split(" ")[1].split(".")[0]
    canary_secret = "CANARY_WRONG_SECRET_VALUE"
    api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": f"Bearer {credential_id}.{canary_secret}"},
    )

    events = asyncio.run(_authentication_failed_events(session_factory, "tenant-a"))
    serialized = json.dumps([event.metadata_json for event in events])
    assert canary_secret not in serialized
    assert canary_secret not in (events[0].actor_id or "")
