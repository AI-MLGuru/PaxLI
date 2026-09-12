"""WF-HV-004: idempotency warfare, through the real HTTP layer.

The extensive existing coverage (tests/unit/test_verification_session_idempotency.py,
tests/integration/test_verification_session_idempotency.py, and their
evidence-submission counterparts) already proves converge-on-match,
reject-on-mismatch, tenant-scoping, and concurrent-insert recovery, at
both the unit and real-Postgres-concurrency level. This file targets two
specific gaps that survey found nothing covering:

1. Retry-after-failure: a client that received a 503 (required audit
   persistence failed, the whole attempt rolled back -- proven by
   tests/contracts/security/test_audit_ordering.py) must be able to
   retry with the IDENTICAL Idempotency-Key once the outage clears and
   actually succeed. Nothing durable exists from the failed attempt to
   converge on or collide with -- a system that treated the key as
   "already used" here would permanently strand the client.
2. Audit-dedup-on-replay: an idempotent replay must produce exactly one
   audit event for the governed action, never a second one recorded
   against the router's own unconditional post-create/post-upload audit
   call.
"""

from apps.api.paxli_api.dependencies import get_audit_service
from apps.api.paxli_api.main import app
from core.audit.service import AuditService
from tests.conftest import MINIMAL_JPEG_BYTES


class FailingAuditEventRepository:
    """Simulates a durable audit-persistence outage -- same shape as
    tests/contracts/security/test_audit_ordering.py's, duplicated locally
    rather than imported to keep this file's failure scenario
    self-contained and independently readable."""

    async def add(self, event, dedupe_key=None):
        raise RuntimeError("simulated audit persistence outage")

    async def get_by_dedupe_key(self, tenant_id, session_id, dedupe_key):
        return None

    async def list_for_session(self, session_id, tenant_id):
        return []


def _create_session(api_client, token: str) -> str:
    response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": token},
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


def test_retry_with_the_same_key_succeeds_after_a_failed_first_session_creation(
    api_client, issued_credentials
) -> None:
    token = issued_credentials["tenant_a_operational"]
    idempotency_key = "hv-004-retry-after-outage"

    async def failing_get_audit_service():
        yield AuditService(FailingAuditEventRepository())

    app.dependency_overrides[get_audit_service] = failing_get_audit_service
    try:
        first_attempt = api_client.post(
            "/v1/verification-sessions",
            json={"assurance_level": "STANDARD"},
            headers={"Authorization": token, "Idempotency-Key": idempotency_key},
        )
    finally:
        del app.dependency_overrides[get_audit_service]

    assert first_attempt.status_code == 503

    # Outage has cleared -- retry with the IDENTICAL key. Nothing durable
    # exists from the failed attempt (proven generically by
    # test_no_session_row_is_left_behind_after_required_audit_failure);
    # this must succeed as a genuinely fresh creation, not be rejected as
    # IDEMPOTENCY_KEY_REUSED or silently no-op.
    retry = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": token, "Idempotency-Key": idempotency_key},
    )
    assert retry.status_code == 201
    assert retry.json()["data"]["status"] == "CREATED"

    # And the key now genuinely IS used -- a THIRD attempt with a
    # materially different body under the same key must be rejected,
    # proving the retry's success was real and durable, not another
    # phantom that a third attempt could also silently bypass.
    third_attempt = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "HIGH"},
        headers={"Authorization": token, "Idempotency-Key": idempotency_key},
    )
    assert third_attempt.status_code == 409


def test_retry_with_the_same_key_succeeds_after_a_failed_first_evidence_upload(
    api_client, issued_credentials
) -> None:
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)
    idempotency_key = "hv-004-evidence-retry-after-outage"

    async def failing_get_audit_service():
        yield AuditService(FailingAuditEventRepository())

    app.dependency_overrides[get_audit_service] = failing_get_audit_service
    try:
        first_attempt = api_client.post(
            f"/v1/verification-sessions/{session_id}/selfie",
            files={"file": ("selfie.jpg", MINIMAL_JPEG_BYTES, "image/jpeg")},
            headers={"Authorization": token, "Idempotency-Key": idempotency_key},
        )
    finally:
        del app.dependency_overrides[get_audit_service]

    assert first_attempt.status_code == 503

    retry = api_client.post(
        f"/v1/verification-sessions/{session_id}/selfie",
        files={"file": ("selfie.jpg", MINIMAL_JPEG_BYTES, "image/jpeg")},
        headers={"Authorization": token, "Idempotency-Key": idempotency_key},
    )
    assert retry.status_code == 201


def test_idempotent_replay_of_session_creation_records_exactly_one_audit_event(
    api_client, issued_credentials
) -> None:
    token = issued_credentials["tenant_a_operational"]
    idempotency_key = "hv-004-audit-dedup-session"

    first = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": token, "Idempotency-Key": idempotency_key},
    )
    assert first.status_code == 201
    session_id = first.json()["data"]["id"]

    second = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": token, "Idempotency-Key": idempotency_key},
    )
    assert second.status_code == 201
    assert second.json()["data"]["id"] == session_id  # converged, not a second session

    audit_response = api_client.get(
        f"/v1/verification-sessions/{session_id}/audit-events", headers={"Authorization": token}
    )
    created_events = [
        e for e in audit_response.json()["data"] if e["event_type"] == "SESSION_CREATED"
    ]
    assert len(created_events) == 1  # the replay's own audit call deduped against the first


def test_idempotent_replay_of_evidence_submission_records_exactly_one_audit_event(
    api_client, issued_credentials
) -> None:
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)
    idempotency_key = "hv-004-audit-dedup-evidence"

    first = api_client.post(
        f"/v1/verification-sessions/{session_id}/selfie",
        files={"file": ("selfie.jpg", MINIMAL_JPEG_BYTES, "image/jpeg")},
        headers={"Authorization": token, "Idempotency-Key": idempotency_key},
    )
    assert first.status_code == 201
    evidence_id = first.json()["id"]

    second = api_client.post(
        f"/v1/verification-sessions/{session_id}/selfie",
        files={"file": ("selfie.jpg", MINIMAL_JPEG_BYTES, "image/jpeg")},
        headers={"Authorization": token, "Idempotency-Key": idempotency_key},
    )
    assert second.status_code == 201
    assert second.json()["id"] == evidence_id  # converged, not a second evidence row

    audit_response = api_client.get(
        f"/v1/verification-sessions/{session_id}/audit-events", headers={"Authorization": token}
    )
    uploaded_events = [
        e for e in audit_response.json()["data"] if e["event_type"] == "EVIDENCE_UPLOADED"
    ]
    assert len(uploaded_events) == 1
