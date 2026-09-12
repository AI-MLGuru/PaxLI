"""WF-HV-006: failure injection targeting the exact gap WF-006 disclosed
as Finding G/E -- no test previously injected a genuine DB failure inside
DecisionOrchestrator.evaluate_and_persist()'s own read steps
(session_service.get(), policy_service.get_version(),
evidence_result_service.list_effective_for_session()), which sit outside
PostgresOperationError's guarded-commit-only wrapping and, before this
phase, outside any exception handler at all -- a raw exception there
propagated past every specific handler in main.py and fell through to
Starlette's bare, non-JSON "Internal Server Error" text.

Confirmed live before any fix: correct 500 status, state-safe (no
corrupted session, no fabricated decision), but a genuine client-visible
violation of this app's own {error: {...}, meta: {...}} contract.
Closed with an additive `@app.exception_handler(Exception)` catch-all in
main.py -- no DE-003/DE-004 semantic change, no change to any specific
handler's own behavior (Starlette resolves by exception-class
specificity, not registration order, so the catch-all can never shadow
a more specific handler; the full tests/contracts/ suite re-confirms
this directly).

Uses api_client (SQLite + FakeObjectStorage), matching every other
router-level test in this suite -- the failure is injected via
unittest.mock.patch.object on the real repository class, so the code
path exercised is genuine regardless of which database sits underneath;
what this test proves is the HTTP-layer contract, not database-specific
behavior.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.paxli_api.main import app
from infrastructure.database.models.decision import DecisionRecord
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.policy import SqlAlchemyVerificationPolicyRepository


async def test_db_failure_during_policy_read_fails_safely_with_the_correct_contract(
    api_client, issued_credentials, session_factory
) -> None:
    """Attacks the exact boundary WF-006 Finding G/E named: a genuine DB
    failure inside evaluate_and_persist()'s policy read, reached through
    the real /submit HTTP path against a session already in PROCESSING
    (the crash-recovery shape). Verifies FOUR things, not merely "an
    error occurred": the response is the app's own ErrorEnvelope shape
    (not Starlette's bare text), the underlying exception text is never
    leaked to the client, the session's lifecycle state survives
    uncorrupted, and no decision is fabricated or orphaned.
    """
    token = issued_credentials["tenant_a_operational"]
    create_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": token},
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["data"]["id"]

    async with session_factory() as session:
        record = await session.get(VerificationSessionRecord, session_id)
        record.status = "PROCESSING"
        await session.commit()

    # raise_server_exceptions=False mirrors a real ASGI server (uvicorn):
    # the exception is caught at the protocol boundary, not propagated
    # into the test process itself -- api_client's default TestClient
    # configuration re-raises instead, which is a testing convenience,
    # not what a real deployed client would observe.
    real_client = TestClient(app, raise_server_exceptions=False)
    with patch.object(
        SqlAlchemyVerificationPolicyRepository,
        "get_version",
        side_effect=RuntimeError("simulated DB outage during policy read"),
    ):
        response = real_client.post(
            f"/v1/verification-sessions/{session_id}/submit",
            headers={"Authorization": token},
        )

    assert response.status_code == 500
    body = response.json()  # must be valid JSON, not Starlette's bare text
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "meta" in body and "request_id" in body["meta"]
    # The underlying exception text must never reach the client.
    assert "simulated DB outage" not in response.text
    assert "RuntimeError" not in response.text

    # State-safety: the session survives exactly where it was, no
    # corruption, no premature terminal transition.
    async with session_factory() as verify_session:
        record = await verify_session.get(VerificationSessionRecord, session_id)
        assert record.status == "PROCESSING"
        result = await verify_session.execute(
            select(DecisionRecord).where(DecisionRecord.session_id == session_id)
        )
        assert result.scalars().all() == []  # no orphaned/fabricated decision

    # Real retry, unpatched: converges cleanly to exactly one decision.
    retry = api_client.post(
        f"/v1/verification-sessions/{session_id}/submit", headers={"Authorization": token}
    )
    assert retry.status_code == 200
    assert retry.json()["data"]["status"] == "COMPLETED"
    async with session_factory() as verify_session:
        result = await verify_session.execute(
            select(DecisionRecord).where(DecisionRecord.session_id == session_id)
        )
        assert len(result.scalars().all()) == 1


def test_unhandled_exception_handler_never_shadows_a_specific_handler(api_client) -> None:
    """The new catch-all must remain strictly lower-priority than every
    existing specific handler -- proven directly, not merely inferred
    from Starlette's documented MRO-based resolution. Attacks
    AuthenticationError (a subclass of Exception with its own registered
    handler) by omitting the Authorization header entirely, and confirms
    the SPECIFIC handler's exact response shape still fires, not the
    generic one."""
    response = api_client.get("/v1/verification-sessions/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 401  # AuthenticationError's own handler, not 500
    assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"
