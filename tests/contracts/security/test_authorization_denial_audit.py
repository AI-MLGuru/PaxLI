"""Requirement traceability: SEC-7.29.1, Invariant 12.9 (12.42/12.46), Invariant 12.14/12.15.

An authorization denial is a security-relevant action and must leave a
durable audit event. A failure to durably record that denial must not be
silently discarded, and must not be reported to the caller as an ordinary
successful denial.
"""

from sqlalchemy import select

from apps.api.averiq_api.main import app
from infrastructure.database.models.audit_event import AuditEventRecord


async def _authorization_denied_events(session_factory, tenant_id: str) -> list[AuditEventRecord]:
    async with session_factory() as session:
        result = await session.execute(
            select(AuditEventRecord).where(
                AuditEventRecord.tenant_id == tenant_id,
                AuditEventRecord.event_type == "AUTHORIZATION_DENIED",
            )
        )
        return list(result.scalars().all())


def test_authorization_denial_is_durably_audited(
    api_client, issued_credentials, session_factory
) -> None:
    import asyncio

    response = api_client.post(
        "/v1/management/credentials",
        json={"name": "should-be-denied", "scope": "OPERATIONAL"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert response.status_code == 403

    events = asyncio.run(_authorization_denied_events(session_factory, "tenant-a"))
    assert len(events) == 1
    assert events[0].actor_type == "CLIENT"
    assert events[0].actor_id is not None
    assert events[0].status == "FAILURE"
    assert events[0].metadata_json["required_permission"] == "credential:manage"


def test_authorization_denial_audit_failure_does_not_silently_return_plain_403(
    api_client, issued_credentials
) -> None:
    """If the required denial-audit event cannot be persisted, the caller
    must see that a security control failed, not an ordinary 403 that
    implies the denial was normally and durably recorded."""

    class BrokenSessionFactory:
        def __call__(self):
            raise RuntimeError("simulated audit database outage")

    original = app.state.db_session_factory
    app.state.db_session_factory = BrokenSessionFactory()
    try:
        response = api_client.post(
            "/v1/management/credentials",
            json={"name": "should-be-denied", "scope": "OPERATIONAL"},
            headers={"Authorization": issued_credentials["tenant_a_operational"]},
        )
    finally:
        app.state.db_session_factory = original

    assert response.status_code == 500 or response.status_code == 503


def test_authorization_denial_error_response_never_leaks_permission_internals(
    api_client, issued_credentials
) -> None:
    """SEC-7.4.6: authorization failures must not expose unnecessary protected
    resource/internal information in the response body."""
    response = api_client.post(
        "/v1/management/credentials",
        json={"name": "should-be-denied", "scope": "OPERATIONAL"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    body = response.json()
    assert body["error"]["message"] == "Operation not permitted"
    assert "credential:manage" not in body["error"]["message"]
