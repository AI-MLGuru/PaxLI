"""WF-HV-003: lifecycle state-machine attacks through the real HTTP/API
layer. Not a re-demonstration of the happy path (tests/integration/
test_session_lifecycle.py already has that) -- each test here targets a
specific transition sequence no earlier phase's suite attacked: cancel
twice, cancel after completion, cancel during processing, and submit
against a session that expired lazily rather than explicitly. The goal
is an impossible state or a silently-wrong response, not merely a
non-200 status code.
"""

from datetime import UTC, datetime, timedelta

from infrastructure.database.models.verification_session import VerificationSessionRecord


def _create_session(api_client, token: str) -> str:
    response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": token},
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


def _get(api_client, session_id: str, token: str):
    return api_client.get(
        f"/v1/verification-sessions/{session_id}", headers={"Authorization": token}
    )


def _cancel(api_client, session_id: str, token: str):
    return api_client.post(
        f"/v1/verification-sessions/{session_id}/cancel", headers={"Authorization": token}
    )


def _submit(api_client, session_id: str, token: str):
    return api_client.post(
        f"/v1/verification-sessions/{session_id}/submit", headers={"Authorization": token}
    )


def _parse(timestamp: str) -> datetime:
    """SQLite's driver (this file's api_client fixture) drops timezone
    awareness on read, while a freshly-transitioned in-memory object
    still carries it -- Pydantic serializes the two differently (a
    trailing 'Z' only for timezone-aware values), even though the
    underlying instant is identical. Real Postgres's TIMESTAMPTZ columns
    round-trip awareness correctly; this normalization exists only
    because these particular tests compare a value across that specific
    round-trip boundary."""
    return datetime.fromisoformat(timestamp.removesuffix("Z")).replace(tzinfo=UTC)


def test_cancelling_an_already_cancelled_session_is_409_not_a_second_cancellation(
    api_client, issued_credentials
) -> None:
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)

    first = _cancel(api_client, session_id, token)
    second = _cancel(api_client, session_id, token)

    assert first.status_code == 200
    assert first.json()["data"]["status"] == "CANCELLED"
    assert second.status_code == 409
    # the session is not corrupted by the rejected second attempt
    get_response = _get(api_client, session_id, token)
    assert get_response.json()["data"]["status"] == "CANCELLED"
    first_completed_at = _parse(first.json()["data"]["completed_at"])
    second_read_completed_at = _parse(get_response.json()["data"]["completed_at"])
    assert second_read_completed_at == first_completed_at  # never re-stamped


def test_cancelling_a_completed_session_is_409_and_never_touches_the_decision(
    api_client, issued_credentials
) -> None:
    """WF-4.18.5: cancellation MUST NOT change an already committed
    decision. Attack it directly: try to cancel a session that has
    already reached COMPLETED with a real decision, and confirm both
    the lifecycle status and the decision projection are byte-identical
    before and after the rejected attempt."""
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)
    submit_response = _submit(api_client, session_id, token)
    assert submit_response.status_code == 200
    original_decision = submit_response.json()["data"]["decision"]
    assert original_decision is not None

    cancel_response = _cancel(api_client, session_id, token)
    assert cancel_response.status_code == 409

    get_response = _get(api_client, session_id, token)
    assert get_response.json()["data"]["status"] == "COMPLETED"  # never became CANCELLED
    assert get_response.json()["data"]["decision"] == original_decision  # untouched, byte-identical


async def test_cancelling_a_processing_session_succeeds_and_a_later_submit_is_then_409(
    api_client, issued_credentials, session_factory
) -> None:
    """PROCESSING is legal-to-cancel (WF-001 §6: legal from every
    non-terminal state). Attack the follow-on: once cancelled from
    PROCESSING, a subsequent /submit attempt (a client that didn't yet
    know about the cancellation, retrying) must be rejected outright --
    never resume evaluation, never silently produce a decision for a
    session the tenant explicitly terminated."""
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)
    async with session_factory() as session:
        record = await session.get(VerificationSessionRecord, session_id)
        record.status = "PROCESSING"
        await session.commit()

    cancel_response = _cancel(api_client, session_id, token)
    assert cancel_response.status_code == 200
    assert cancel_response.json()["data"]["status"] == "CANCELLED"

    submit_response = _submit(api_client, session_id, token)
    assert submit_response.status_code == 409

    get_response = _get(api_client, session_id, token)
    assert get_response.json()["data"]["status"] == "CANCELLED"
    assert get_response.json()["data"]["decision"] is None  # no decision was ever produced


async def test_submit_against_a_lazily_expired_session_is_409_not_a_silent_completion(
    api_client, issued_credentials, session_factory
) -> None:
    """A session past its deadline while still CREATED transitions to
    EXPIRED lazily, on the very first read submit() itself performs
    (VerificationSessionService.get() inside VerificationWorkflowService.
    submit()) -- not through any explicit client action. Attack the
    ordering: call /submit directly against a session whose deadline
    already passed, and confirm it resolves to the terminal EXPIRED
    rejection, never treats the pre-expiry CREATED status as still valid
    and runs evaluation anyway."""
    token = issued_credentials["tenant_a_operational"]
    session_id = _create_session(api_client, token)
    async with session_factory() as session:
        record = await session.get(VerificationSessionRecord, session_id)
        record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    submit_response = _submit(api_client, session_id, token)
    assert submit_response.status_code == 409

    get_response = _get(api_client, session_id, token)
    assert get_response.json()["data"]["status"] == "EXPIRED"
    assert get_response.json()["data"]["decision"] is None  # EXPIRED never carries a decision

    audit_response = api_client.get(
        f"/v1/verification-sessions/{session_id}/audit-events", headers={"Authorization": token}
    )
    event_types = [event["event_type"] for event in audit_response.json()["data"]]
    assert "SESSION_EXPIRED" in event_types  # WF-006 Finding B: audited regardless of trigger path
