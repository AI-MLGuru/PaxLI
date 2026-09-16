"""Requirement traceability: SEC-7.22.1, SEC-7.22.2, SEC-7.22.4."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.paxli_api.dependencies import get_audit_service, get_evidence_service
from apps.api.paxli_api.main import app
from core.evidence.enums import EvidenceSource
from core.evidence.media_validation import UnsupportedMediaError, verify_evidence_media
from core.evidence.models import Evidence
from tests.conftest import MINIMAL_JPEG_BYTES


class _FailOnSecondEvidenceService:
    def __init__(self, *, fail_on_second: bool = True) -> None:
        self.fail_on_second = fail_on_second
        self.attempted: list[bytes] = []
        self.persisted: list[Evidence] = []

    async def add(self, **kwargs: Any) -> Evidence:
        content = kwargs["content"]
        self.attempted.append(content)
        if self.fail_on_second and len(self.attempted) == 2:
            raise RuntimeError("simulated frame-2 persistence failure")
        evidence = Evidence(
            session_id=kwargs["session_id"],
            tenant_id=kwargs["tenant_id"],
            evidence_type=kwargs["evidence_type"],
            source=EvidenceSource.CLIENT,
            object_key=f"test/{len(self.persisted)}",
            checksum=kwargs["checksum"],
            mime_type="image/jpeg",
            size_bytes=len(content),
            metadata=kwargs["metadata"],
            retention_until=datetime.now(UTC) + timedelta(days=30),
        )
        self.persisted.append(evidence)
        return evidence


class _FailingAuditService:
    async def record(self, **kwargs: Any) -> None:
        raise RuntimeError("simulated required audit failure")


def test_verify_evidence_media_detects_real_jpeg_regardless_of_claimed_type() -> None:
    assert verify_evidence_media(MINIMAL_JPEG_BYTES) == "image/jpeg"


def test_verify_evidence_media_rejects_arbitrary_bytes() -> None:
    import pytest

    with pytest.raises(UnsupportedMediaError):
        verify_evidence_media(b"not an image, just text pretending to be one")


def test_upload_is_rejected_when_the_client_mime_type_lies_about_the_content(
    api_client, issued_credentials
) -> None:
    """SEC-7.22.2: file type validation MUST NOT rely solely on the client's
    declared Content-Type -- a request claiming image/jpeg with non-image
    bytes must be rejected regardless of the header."""
    create_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    session_id = create_response.json()["data"]["id"]

    response = api_client.post(
        f"/v1/verification-sessions/{session_id}/selfie",
        files={"file": ("selfie.jpg", b"this is not actually a jpeg", "image/jpeg")},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert response.status_code == 415


def test_stored_mime_type_reflects_verified_bytes_not_the_client_header(
    api_client, issued_credentials
) -> None:
    """A client claiming the wrong (but still valid-image) Content-Type must
    have the server-detected type recorded, not the client's claim."""
    create_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    session_id = create_response.json()["data"]["id"]

    response = api_client.post(
        f"/v1/verification-sessions/{session_id}/selfie",
        files={"file": ("selfie.png", MINIMAL_JPEG_BYTES, "image/png")},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert response.status_code == 201
    assert response.json()["mime_type"] == "image/jpeg"


def test_liveness_accepts_bounded_frames_and_lists_each_capture(
    api_client, issued_credentials
) -> None:
    create_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    session_id = create_response.json()["data"]["id"]
    files = [
        ("frames", ("frame-1.jpg", MINIMAL_JPEG_BYTES + b"FRAME_1", "image/jpeg")),
        ("frames", ("frame-2.jpg", MINIMAL_JPEG_BYTES + b"FRAME_2", "image/jpeg")),
    ]

    response = api_client.post(
        f"/v1/verification-sessions/{session_id}/liveness",
        files=files,
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )

    assert response.status_code == 201
    listed = api_client.get(
        f"/v1/verification-sessions/{session_id}/evidence",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert listed.status_code == 200
    liveness = [
        item for item in listed.json()["data"] if item["evidence_type"] == "LIVENESS"
    ]
    assert len(liveness) == 2
    assert response.json()["id"] == liveness[-1]["id"]


@pytest.mark.parametrize("frame_count, expected_status", [(0, 422), (1, 201), (5, 201), (6, 422)])
def test_liveness_frame_cardinality_matrix(
    api_client, issued_credentials, frame_count: int, expected_status: int
) -> None:
    create_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    session_id = create_response.json()["data"]["id"]
    files = [
        ("frames", (f"frame-{index}.jpg", MINIMAL_JPEG_BYTES, "image/jpeg"))
        for index in range(frame_count)
    ]

    response = api_client.post(
        f"/v1/verification-sessions/{session_id}/liveness",
        files=files,
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )

    assert response.status_code == expected_status


def test_liveness_rejects_more_than_five_frames_before_persistence(
    api_client, issued_credentials
) -> None:
    create_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    session_id = create_response.json()["data"]["id"]
    files = [
        ("frames", (f"frame-{index}.jpg", MINIMAL_JPEG_BYTES, "image/jpeg"))
        for index in range(6)
    ]

    response = api_client.post(
        f"/v1/verification-sessions/{session_id}/liveness",
        files=files,
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )

    assert response.status_code == 422
    listed = api_client.get(
        f"/v1/verification-sessions/{session_id}/evidence",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert listed.status_code == 200
    assert not [
        item for item in listed.json()["data"] if item["evidence_type"] == "LIVENESS"
    ]


def test_liveness_idempotency_is_derived_per_frame(
    api_client, issued_credentials
) -> None:
    create_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    session_id = create_response.json()["data"]["id"]
    headers = {
        "Authorization": issued_credentials["tenant_a_operational"],
        "Idempotency-Key": "liveness-batch-1",
    }
    files = [
        ("frames", ("frame-1.jpg", MINIMAL_JPEG_BYTES + b"FRAME_1", "image/jpeg")),
        ("frames", ("frame-2.jpg", MINIMAL_JPEG_BYTES + b"FRAME_2", "image/jpeg")),
    ]

    first = api_client.post(
        f"/v1/verification-sessions/{session_id}/liveness", files=files, headers=headers
    )
    replay = api_client.post(
        f"/v1/verification-sessions/{session_id}/liveness", files=files, headers=headers
    )
    changed = api_client.post(
        f"/v1/verification-sessions/{session_id}/liveness",
        files=[
            ("frames", ("frame-1.jpg", MINIMAL_JPEG_BYTES + b"CHANGED", "image/jpeg")),
            ("frames", ("frame-2.jpg", MINIMAL_JPEG_BYTES + b"FRAME_2", "image/jpeg")),
        ],
        headers=headers,
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert changed.status_code == 409


def test_liveness_frame_two_failure_is_partial_and_stops_before_frame_three(
    api_client, issued_credentials
) -> None:
    create_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    session_id = create_response.json()["data"]["id"]
    service = _FailOnSecondEvidenceService()

    async def override_get_evidence_service() -> _FailOnSecondEvidenceService:
        return service

    app.dependency_overrides[get_evidence_service] = override_get_evidence_service
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            f"/v1/verification-sessions/{session_id}/liveness",
            files=[
                ("frames", ("frame-1.jpg", MINIMAL_JPEG_BYTES + b"ONE", "image/jpeg")),
                ("frames", ("frame-2.jpg", MINIMAL_JPEG_BYTES + b"TWO", "image/jpeg")),
                ("frames", ("frame-3.jpg", MINIMAL_JPEG_BYTES + b"THREE", "image/jpeg")),
            ],
            headers={"Authorization": issued_credentials["tenant_a_operational"]},
        )
    finally:
        app.dependency_overrides.pop(get_evidence_service, None)

    assert response.status_code == 500
    assert len(service.attempted) == 2
    assert service.attempted[0].endswith(b"ONE")
    assert service.attempted[1].endswith(b"TWO")
    assert len(service.persisted) == 1


def test_liveness_audit_failure_returns_error_after_capture_persistence(
    api_client, issued_credentials
) -> None:
    create_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    session_id = create_response.json()["data"]["id"]
    service = _FailOnSecondEvidenceService(fail_on_second=False)

    async def override_get_evidence_service() -> _FailOnSecondEvidenceService:
        return service

    async def override_get_audit_service() -> _FailingAuditService:
        return _FailingAuditService()

    app.dependency_overrides[get_evidence_service] = override_get_evidence_service
    app.dependency_overrides[get_audit_service] = override_get_audit_service
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            f"/v1/verification-sessions/{session_id}/liveness",
            files=[("frames", ("frame-1.jpg", MINIMAL_JPEG_BYTES, "image/jpeg"))],
            headers={"Authorization": issued_credentials["tenant_a_operational"]},
        )
    finally:
        app.dependency_overrides.pop(get_evidence_service, None)
        app.dependency_overrides.pop(get_audit_service, None)

    assert response.status_code == 500
    assert len(service.persisted) == 1
