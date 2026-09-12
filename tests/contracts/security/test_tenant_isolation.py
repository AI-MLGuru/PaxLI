"""Requirement traceability: SEC-7.5.*, PRV-11.11.*, PRV-11.19.*, Invariant 08.

WF-HV-002: tenant isolation, attacked rather than merely demonstrated --
the tests below this module's original five specifically target surfaces
no earlier phase's test suite reached: cancel, idempotency-key collision
across tenants (both session-creation and evidence-submission), and the
GET-triggered PROCESSING recovery WF-006 Finding A added, which is new
enough surface that a tenant-scoping mistake there would have gone
unnoticed by every pre-existing test.
"""

from infrastructure.database.models.verification_session import VerificationSessionRecord
from tests.conftest import MINIMAL_JPEG_BYTES


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
    upload_response = api_client.post(
        f"/v1/verification-sessions/{session_id}/selfie",
        files={"file": ("selfie.jpg", MINIMAL_JPEG_BYTES + b"CANARY_SELFIE_BYTES", "image/jpeg")},
        headers={"Authorization": issued_credentials["tenant_b_operational"]},
    )
    assert upload_response.status_code == 201

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


def test_cross_tenant_cancel_is_denied(api_client, issued_credentials) -> None:
    """WF-HV-002: no existing test attacked /cancel specifically -- an
    attacker's cancel attempt against another tenant's session must fail
    exactly like a read would, and must not actually cancel the victim's
    session as a side effect of the failed attempt."""
    session_id = _create_session(api_client, issued_credentials["tenant_b_operational"])

    response = api_client.post(
        f"/v1/verification-sessions/{session_id}/cancel",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert response.status_code == 404

    victim_view = api_client.get(
        f"/v1/verification-sessions/{session_id}",
        headers={"Authorization": issued_credentials["tenant_b_operational"]},
    )
    assert victim_view.json()["data"]["status"] == "CREATED"  # untouched by the denied attempt


def test_cross_tenant_idempotency_key_reuse_creates_independent_sessions(
    api_client, issued_credentials
) -> None:
    """WF-HV-002 / WF-4.9.4: the identical raw Idempotency-Key value,
    reused by two different tenants for an identical request body, must
    never cause tenant B's request to converge on tenant A's session (a
    false convergence that would leak session identity across the tenant
    boundary), and must never be rejected as IDEMPOTENCY_KEY_REUSED
    either (a false conflict from a key collision that was never actually
    the same logical operation, since it belongs to a different tenant)."""
    shared_key = "attacker-chosen-idempotency-key"
    payload = {"assurance_level": "STANDARD"}

    tenant_a_response = api_client.post(
        "/v1/verification-sessions",
        json=payload,
        headers={
            "Authorization": issued_credentials["tenant_a_operational"],
            "Idempotency-Key": shared_key,
        },
    )
    tenant_b_response = api_client.post(
        "/v1/verification-sessions",
        json=payload,
        headers={
            "Authorization": issued_credentials["tenant_b_operational"],
            "Idempotency-Key": shared_key,
        },
    )

    assert tenant_a_response.status_code == 201
    assert tenant_b_response.status_code == 201
    tenant_a_id = tenant_a_response.json()["data"]["id"]
    tenant_b_id = tenant_b_response.json()["data"]["id"]
    assert tenant_a_id != tenant_b_id  # two independent sessions, not one shared/converged row

    # And neither tenant can read the other's session through it -- the
    # key collision created no cross-tenant linkage of any kind.
    cross_read = api_client.get(
        f"/v1/verification-sessions/{tenant_b_id}",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert cross_read.status_code == 404


def test_cross_tenant_evidence_idempotency_key_reuse_creates_independent_evidence(
    api_client, issued_credentials
) -> None:
    """WF-HV-002 / WF-4.9.4: same property as session creation, for
    evidence submission -- evidence idempotency is scoped to
    (tenant_id, session_id, key), so an identical raw key reused by a
    second tenant on its own, independently-created session must produce
    its own independent evidence row, never converge on or collide with
    the first tenant's."""
    shared_key = "attacker-chosen-evidence-idempotency-key"
    tenant_a_session = _create_session(api_client, issued_credentials["tenant_a_operational"])
    tenant_b_session = _create_session(api_client, issued_credentials["tenant_b_operational"])

    tenant_a_upload = api_client.post(
        f"/v1/verification-sessions/{tenant_a_session}/selfie",
        files={"file": ("selfie.jpg", MINIMAL_JPEG_BYTES + b"TENANT_A", "image/jpeg")},
        headers={
            "Authorization": issued_credentials["tenant_a_operational"],
            "Idempotency-Key": shared_key,
        },
    )
    tenant_b_upload = api_client.post(
        f"/v1/verification-sessions/{tenant_b_session}/selfie",
        files={"file": ("selfie.jpg", MINIMAL_JPEG_BYTES + b"TENANT_B", "image/jpeg")},
        headers={
            "Authorization": issued_credentials["tenant_b_operational"],
            "Idempotency-Key": shared_key,
        },
    )

    assert tenant_a_upload.status_code == 201
    assert tenant_b_upload.status_code == 201
    assert tenant_a_upload.json()["id"] != tenant_b_upload.json()["id"]
    assert tenant_a_upload.json()["checksum"] != tenant_b_upload.json()["checksum"]


async def test_cross_tenant_get_never_triggers_recovery_on_another_tenants_processing_session(
    api_client, issued_credentials, session_factory
) -> None:
    """WF-HV-002, targeting WF-006 Finding A's new surface specifically:
    a session found in PROCESSING now causes GET to perform real work
    (VerificationWorkflowService.submit()) -- this must remain exactly as
    tenant-scoped as a plain read. Tenant A must not be able to trigger
    (or even detect the existence of) tenant B's stuck session by
    guessing its ID, and the recovery must not run against a session A
    was never authorized to touch."""
    session_id = _create_session(api_client, issued_credentials["tenant_b_operational"])
    async with session_factory() as session:
        record = await session.get(VerificationSessionRecord, session_id)
        record.status = "PROCESSING"
        await session.commit()

    attacker_response = api_client.get(
        f"/v1/verification-sessions/{session_id}",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert attacker_response.status_code == 404

    # The victim's session must be untouched by the denied attempt --
    # still stuck in PROCESSING, not silently recovered as a side effect
    # of an unauthorized read that should never have reached it.
    async with session_factory() as verify_session:
        record = await verify_session.get(VerificationSessionRecord, session_id)
        assert record.status == "PROCESSING"

    # The legitimate owner's own GET, by contrast, must still self-heal.
    owner_response = api_client.get(
        f"/v1/verification-sessions/{session_id}",
        headers={"Authorization": issued_credentials["tenant_b_operational"]},
    )
    assert owner_response.status_code == 200
    assert owner_response.json()["data"]["status"] == "COMPLETED"
