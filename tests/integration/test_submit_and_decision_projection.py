"""WF-001 §2-4/§9/§12: POST /verification-sessions/{id}/submit and the
session GET decision projection, through the real HTTP/API layer (api_client
-- SQLite + FakeObjectStorage, matching every other router-level test in
this suite; the underlying CAS/idempotency mechanics are already proven
against real Postgres in tests/integration/test_verification_workflow.py
and test_verification_session_idempotency.py). These tests exercise the
NEW surface WF-005 adds: routing, response shape, tenant isolation, and
error mapping.
"""

from core.audit.service import AuditService
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.policy import SqlAlchemyVerificationPolicyRepository


def _create_session(api_client, token: str) -> str:
    response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": token},
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


async def _force_session_to_processing(session_factory, session_id: str) -> None:
    """Test-only direct write, simulating a /submit call that reached
    PROCESSING and then crashed before reaching COMPLETED -- never how a
    real request would get here (VerificationSessionService.transition()'s
    CAS write is exactly what this deliberately bypasses); this exists
    only to construct the crash scenario itself. The session must already
    carry a valid policy pin (created normally via api_client first) for
    the subsequent recovery attempt to have anything to evaluate."""
    async with session_factory() as session:
        record = await session.get(VerificationSessionRecord, session_id)
        record.status = "PROCESSING"
        await session.commit()


def test_created_session_has_a_null_decision_projection(api_client, issued_credentials) -> None:
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)

    response = api_client.get(
        f"/v1/verification-sessions/{session_id}", headers={"Authorization": token}
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CREATED"
    assert response.json()["data"]["decision"] is None


def test_submit_from_created_completes_with_a_populated_decision_projection(
    api_client, issued_credentials
) -> None:
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)

    response = api_client.post(
        f"/v1/verification-sessions/{session_id}/submit", headers={"Authorization": token}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "COMPLETED"
    assert data["decision"] is not None
    # The fixture-seeded policy has no default_outcome configured (nullable,
    # falls back to INCONCLUSIVE/NO_MATCHING_RULE, DE-003 §10) -- the exact
    # outcome value is incidental here; what this test proves is that the
    # workflow ran end to end and the projection is populated and shaped
    # correctly.
    assert data["decision"]["outcome"] == "INCONCLUSIVE"
    assert "NO_MATCHING_RULE" in data["decision"]["reason_codes"][0]
    assert data["decision"]["policy"]["id"]
    assert data["decision"]["policy"]["version"] == 1
    assert data["decision"]["policy"]["hash"]


def test_get_after_submit_shows_the_same_decision_projection(
    api_client, issued_credentials
) -> None:
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)
    submit_response = api_client.post(
        f"/v1/verification-sessions/{session_id}/submit", headers={"Authorization": token}
    )
    assert submit_response.status_code == 200

    get_response = api_client.get(
        f"/v1/verification-sessions/{session_id}", headers={"Authorization": token}
    )

    assert get_response.status_code == 200
    assert get_response.json()["data"]["decision"] == submit_response.json()["data"]["decision"]


def test_submit_is_idempotent_on_replay(api_client, issued_credentials) -> None:
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)

    first = api_client.post(
        f"/v1/verification-sessions/{session_id}/submit", headers={"Authorization": token}
    )
    second = api_client.post(
        f"/v1/verification-sessions/{session_id}/submit", headers={"Authorization": token}
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["decision"] == second.json()["data"]["decision"]


def test_submit_on_a_cancelled_session_is_409(api_client, issued_credentials) -> None:
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)
    cancel_response = api_client.post(
        f"/v1/verification-sessions/{session_id}/cancel", headers={"Authorization": token}
    )
    assert cancel_response.status_code == 200

    response = api_client.post(
        f"/v1/verification-sessions/{session_id}/submit", headers={"Authorization": token}
    )

    assert response.status_code == 409


def test_submit_on_a_nonexistent_session_is_404(api_client, issued_credentials) -> None:
    token = issued_credentials["tenant_a_operational"]

    response = api_client.post(
        "/v1/verification-sessions/00000000-0000-0000-0000-000000000000/submit",
        headers={"Authorization": token},
    )

    assert response.status_code == 404


def test_cross_tenant_submit_is_denied(api_client, issued_credentials) -> None:
    """SEC-7.5.5 / PRV-11.19.1, same shape as the existing cross-tenant GET
    test: tenant A must not be able to drive tenant B's session through
    processing, and the failure must not distinguish "exists for another
    tenant" from "doesn't exist" (fail closed without revealing protected
    cross-tenant resource existence)."""
    session_id = _create_session(api_client, issued_credentials["tenant_b_operational"])

    response = api_client.post(
        f"/v1/verification-sessions/{session_id}/submit",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )

    assert response.status_code == 404


def test_cross_tenant_get_never_leaks_another_tenants_decision(
    api_client, issued_credentials
) -> None:
    session_id = _create_session(api_client, issued_credentials["tenant_b_operational"])
    submit_response = api_client.post(
        f"/v1/verification-sessions/{session_id}/submit",
        headers={"Authorization": issued_credentials["tenant_b_operational"]},
    )
    assert submit_response.status_code == 200
    assert submit_response.json()["data"]["decision"] is not None

    response = api_client.get(
        f"/v1/verification-sessions/{session_id}",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )

    assert response.status_code == 404


async def test_decision_projection_policy_reference_matches_the_pinned_session_policy(
    api_client, issued_credentials, session_factory
) -> None:
    """WF-001 §9 / DE-003 §16's adversarial matrix, at the API layer: a
    session pins whatever policy version is ACTIVE at creation time
    (DE-002/DE-003 §1 early binding). Activating a second version for the
    same tenant/assurance_level AFTER the session was created, but BEFORE
    submit() runs, must never change what the returned decision's policy
    reference shows -- "policy v3->v4 mid-session: v3 always"."""
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)

    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        v2 = await policy_service.create_and_activate(
            tenant_id="tenant-a",
            policy_id="test-fixture-default-tenant-a",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="test",
        )
        await session.commit()
    assert v2.version == 2  # confirms the fixture-seeded v1 really was superseded

    response = api_client.post(
        f"/v1/verification-sessions/{session_id}/submit", headers={"Authorization": token}
    )

    assert response.status_code == 200
    assert response.json()["data"]["decision"]["policy"]["version"] == 1  # v1, not v2


async def test_get_on_a_stuck_processing_session_self_heals_to_completed(
    api_client, issued_credentials, session_factory
) -> None:
    """WF-001 §4 / WF-006 Finding A: a session found in PROCESSING on a
    plain GET is exactly the shape of an earlier /submit call that
    crashed mid-flight. A client that only polls -- never thinks to retry
    POST /submit specifically -- must still see the session resolve to
    COMPLETED with a populated decision, not sit stuck forever."""
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)
    await _force_session_to_processing(session_factory, session_id)

    response = api_client.get(
        f"/v1/verification-sessions/{session_id}", headers={"Authorization": token}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "COMPLETED"
    assert data["decision"] is not None
    assert data["decision"]["outcome"] == "INCONCLUSIVE"


async def test_get_on_a_stuck_processing_session_is_idempotent_on_repeated_polls(
    api_client, issued_credentials, session_factory
) -> None:
    """A second poll after the session has already self-healed must
    converge on the identical decision, never recompute or duplicate
    one (the same idempotent-replay property /submit itself has, now
    also reachable through GET)."""
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)
    await _force_session_to_processing(session_factory, session_id)

    first = api_client.get(
        f"/v1/verification-sessions/{session_id}", headers={"Authorization": token}
    )
    second = api_client.get(
        f"/v1/verification-sessions/{session_id}", headers={"Authorization": token}
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["decision"] == second.json()["data"]["decision"]


async def test_get_on_a_non_processing_session_never_triggers_recovery_work(
    api_client, issued_credentials
) -> None:
    """The recovery attempt is scoped strictly to PROCESSING -- a session
    that never reached PROCESSING (still CREATED here) must remain a
    plain, unmodified read: no decision, no lifecycle transition."""
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)

    response = api_client.get(
        f"/v1/verification-sessions/{session_id}", headers={"Authorization": token}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "CREATED"
    assert data["decision"] is None
