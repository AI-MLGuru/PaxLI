"""WF-HV-006 / WF-HV-009: failure injection targeting
DecisionOrchestrator.evaluate_and_persist()'s own read steps
(session_service.get(), policy_service.get_version(),
evidence_result_service.list_effective_for_session()), which sit outside
PostgresOperationError's guarded-commit-only wrapping.

Two layers of fix, in sequence:

1. WF-006 Finding G/E (HV-006): before any fix, a raw exception from
   these reads propagated past every specific handler in main.py and
   fell through to Starlette's bare, non-JSON "Internal Server Error"
   text -- confirmed 500-safe (no corrupted session, no fabricated
   decision) but a contract-shape violation. Closed with an additive
   `@app.exception_handler(Exception)` catch-all in main.py.
2. WF-HV-009: the catch-all made a policy/evidence-read failure
   *safe*, but not *resolved* -- a permanent underlying failure (e.g.
   corrupted evidence ciphertext, see
   test_decision_engine_evidence_integrity_failure.py) left the session
   stuck retrying the identical failure forever, with no path to any
   terminal decision. DecisionOrchestrator now catches exactly these two
   read steps itself and persists a safe INCONCLUSIVE decision with a
   stable engine reason code, so this module's remaining test now
   exercises that resolution directly instead of the (superseded) raw
   500 shape.

Uses api_client (SQLite + FakeObjectStorage), matching every other
router-level test in this suite -- the failure is injected via
unittest.mock.patch.object on the real repository class, so the code
path exercised is genuine regardless of which database sits underneath;
what this test proves is the HTTP-layer contract, not database-specific
behavior.
"""

from unittest.mock import patch

from sqlalchemy import select

from infrastructure.database.models.decision import DecisionRecord
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.policy import SqlAlchemyVerificationPolicyRepository


async def test_db_failure_during_policy_read_resolves_to_a_persisted_inconclusive_decision(
    api_client, issued_credentials, session_factory
) -> None:
    """Attacks the exact boundary WF-006 Finding G/E named: a genuine DB
    failure inside evaluate_and_persist()'s policy read, reached through
    the real /submit HTTP path against a session already in PROCESSING
    (the crash-recovery shape).

    Superseded expectation, deliberately: this test previously asserted a
    raw 500 with no persisted decision (WF-006 Finding G/E's original,
    narrower fix -- an additive catch-all exception handler that only
    corrected the HTTP *contract shape*). WF-HV-009 found that policy/
    evidence read failures inside evaluate_and_persist() were still left
    to propagate as unhandled exceptions, which is safe against a
    transient DB blip but leaves a session with a *permanent* underlying
    failure (e.g. corrupted evidence ciphertext -- see
    test_decision_engine_evidence_integrity_failure.py) stuck retrying
    the exact same failure forever, with no path to any terminal
    decision. DecisionOrchestrator now catches exactly these two read
    steps and resolves them to a persisted INCONCLUSIVE decision with a
    stable engine reason code (DEC-5.24/DEC-5.24.3), the same posture
    already used for POLICY_VERSION_UNAVAILABLE/POLICY_INVALID and for
    evaluate()'s own exceptions two branches later in that function.
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

    with patch.object(
        SqlAlchemyVerificationPolicyRepository,
        "get_version",
        side_effect=RuntimeError("simulated DB outage during policy read"),
    ):
        response = api_client.post(
            f"/v1/verification-sessions/{session_id}/submit",
            headers={"Authorization": token},
        )

    # No 500, no crash: the failure resolves to a normal, successful
    # response carrying a safe INCONCLUSIVE decision -- never VERIFIED,
    # never REJECTED, and the underlying exception text is never leaked.
    assert response.status_code == 200
    assert "simulated DB outage" not in response.text
    assert "RuntimeError" not in response.text
    data = response.json()["data"]
    assert data["status"] == "COMPLETED"
    assert data["decision"]["outcome"] == "INCONCLUSIVE"
    assert "ENGINE:POLICY_VERSION_UNAVAILABLE" in data["decision"]["reason_codes"]

    # Durable: exactly one decision persisted, session terminally COMPLETED.
    async with session_factory() as verify_session:
        record = await verify_session.get(VerificationSessionRecord, session_id)
        assert record.status == "COMPLETED"
        result = await verify_session.execute(
            select(DecisionRecord).where(DecisionRecord.session_id == session_id)
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].outcome == "INCONCLUSIVE"

    # Idempotent replay, unpatched: converges on the SAME decision, never
    # a second one and never a retroactively "better" VERIFIED outcome
    # just because the transient-looking failure is now gone (DEC-5.24.1:
    # a decision is made once, ever, per session).
    retry = api_client.post(
        f"/v1/verification-sessions/{session_id}/submit", headers={"Authorization": token}
    )
    assert retry.status_code == 200
    assert retry.json()["data"]["decision"]["outcome"] == "INCONCLUSIVE"
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
