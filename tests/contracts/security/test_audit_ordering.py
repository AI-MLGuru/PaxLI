"""Requirement traceability: Invariant 12, SEC-7.30.1, SEC-7.30.2.

Action -> Required Audit Event -> Durable Audit Acceptance -> Observable Effect.
A required-audit failure MUST block the governed effect; the effect must never
become durably observable without its audit event also being durable.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from apps.api.averiq_api.dependencies import get_audit_service
from apps.api.averiq_api.main import app
from core.audit.models import AuditEvent
from core.audit.service import AuditService
from infrastructure.database.models.credential import CredentialRecordModel
from infrastructure.database.models.evidence import EvidenceRecord
from infrastructure.database.models.verification_session import VerificationSessionRecord
from tests.conftest import MINIMAL_JPEG_BYTES


class FailingAuditEventRepository:
    """Simulates a durable audit-persistence outage."""

    async def add(self, event: AuditEvent, dedupe_key: str | None = None) -> AuditEvent:
        raise RuntimeError("simulated audit persistence outage")

    async def get_by_dedupe_key(
        self, tenant_id: str, session_id: UUID | None, dedupe_key: str
    ) -> AuditEvent | None:
        return None

    async def list_for_session(self, session_id: UUID, tenant_id: str) -> Sequence[AuditEvent]:
        return []


def test_required_audit_failure_blocks_session_creation(
    api_client, issued_credentials, session_factory
) -> None:
    async def failing_get_audit_service():
        yield AuditService(FailingAuditEventRepository())

    app.dependency_overrides[get_audit_service] = failing_get_audit_service
    try:
        response = api_client.post(
            "/v1/verification-sessions",
            json={"assurance_level": "STANDARD"},
            headers={"Authorization": issued_credentials["tenant_a_operational"]},
        )
    finally:
        del app.dependency_overrides[get_audit_service]

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AUDIT_PERSISTENCE_FAILED"


async def _count_tenant_a_sessions(session_factory) -> int:
    async with session_factory() as session:
        result = await session.execute(
            select(VerificationSessionRecord).where(
                VerificationSessionRecord.tenant_id == "tenant-a"
            )
        )
        return len(result.scalars().all())


def test_no_session_row_is_left_behind_after_required_audit_failure(
    api_client, issued_credentials, session_factory
) -> None:
    """The critical property: a failed required audit must not leave the
    governed effect durably persisted (no orphaned session row)."""
    import asyncio

    async def failing_get_audit_service():
        yield AuditService(FailingAuditEventRepository())

    app.dependency_overrides[get_audit_service] = failing_get_audit_service
    try:
        api_client.post(
            "/v1/verification-sessions",
            json={"assurance_level": "STANDARD"},
            headers={"Authorization": issued_credentials["tenant_a_operational"]},
        )
    finally:
        del app.dependency_overrides[get_audit_service]

    assert asyncio.run(_count_tenant_a_sessions(session_factory)) == 0

    # Sanity check: the healthy path does persist a row, proving the count
    # above is a real assertion and not a fixture artifact.
    healthy_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert healthy_response.status_code == 201
    assert asyncio.run(_count_tenant_a_sessions(session_factory)) == 1


def test_audit_events_are_attributed_to_the_authenticated_principal(
    api_client, issued_credentials
) -> None:
    """SEC-7.7.2 / SEC-7.29.2: audit events must identify the authenticated actor."""
    create_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    session_id = create_response.json()["data"]["id"]

    audit_response = api_client.get(
        f"/v1/verification-sessions/{session_id}/audit-events",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    created_event = next(
        event for event in audit_response.json()["data"] if event["event_type"] == "SESSION_CREATED"
    )
    assert created_event["actor_type"] == "CLIENT"
    assert created_event["actor_id"] is not None


async def _count_evidence_rows(session_factory, session_id: str) -> int:
    async with session_factory() as session:
        result = await session.execute(
            select(EvidenceRecord).where(EvidenceRecord.session_id == session_id)
        )
        return len(result.scalars().all())


def test_no_evidence_row_is_left_behind_after_required_audit_failure(
    api_client, issued_credentials, session_factory
) -> None:
    """Invariant-12 remediation 4: proves audit-before-effect at the actual
    public entry point for evidence capture, not just sessions. Previously
    this ordering was only exercised for session creation."""
    import asyncio

    create_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    session_id = create_response.json()["data"]["id"]

    async def failing_get_audit_service():
        yield AuditService(FailingAuditEventRepository())

    app.dependency_overrides[get_audit_service] = failing_get_audit_service
    try:
        response = api_client.post(
            f"/v1/verification-sessions/{session_id}/selfie",
            files={"file": ("selfie.jpg", MINIMAL_JPEG_BYTES, "image/jpeg")},
            headers={"Authorization": issued_credentials["tenant_a_operational"]},
        )
    finally:
        del app.dependency_overrides[get_audit_service]

    assert response.status_code == 503
    assert asyncio.run(_count_evidence_rows(session_factory, session_id)) == 0

    # Sanity check: the healthy path does persist a row.
    healthy_response = api_client.post(
        f"/v1/verification-sessions/{session_id}/selfie",
        files={"file": ("selfie.jpg", MINIMAL_JPEG_BYTES, "image/jpeg")},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert healthy_response.status_code == 201
    assert asyncio.run(_count_evidence_rows(session_factory, session_id)) == 1


async def _count_credentials_named(session_factory, tenant_id: str, name: str) -> int:
    async with session_factory() as session:
        result = await session.execute(
            select(CredentialRecordModel).where(
                CredentialRecordModel.tenant_id == tenant_id,
                CredentialRecordModel.name == name,
            )
        )
        return len(result.scalars().all())


def test_no_credential_row_is_left_behind_after_required_audit_failure(
    api_client, issued_credentials, session_factory
) -> None:
    """Invariant-12 remediation 4: proves audit-before-effect at the actual
    public entry point for credential issuance, not just sessions."""
    import asyncio

    credential_name = "audit-ordering-test-credential"

    async def failing_get_audit_service():
        yield AuditService(FailingAuditEventRepository())

    app.dependency_overrides[get_audit_service] = failing_get_audit_service
    try:
        response = api_client.post(
            "/v1/management/credentials",
            json={"name": credential_name, "scope": "OPERATIONAL"},
            headers={"Authorization": issued_credentials["tenant_a_admin"]},
        )
    finally:
        del app.dependency_overrides[get_audit_service]

    assert response.status_code == 503
    assert asyncio.run(_count_credentials_named(session_factory, "tenant-a", credential_name)) == 0

    # Sanity check: the healthy path does persist a row.
    healthy_response = api_client.post(
        "/v1/management/credentials",
        json={"name": credential_name, "scope": "OPERATIONAL"},
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )
    assert healthy_response.status_code == 201
    assert asyncio.run(_count_credentials_named(session_factory, "tenant-a", credential_name)) == 1
