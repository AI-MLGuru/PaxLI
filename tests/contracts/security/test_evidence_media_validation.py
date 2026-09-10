"""Requirement traceability: SEC-7.22.1, SEC-7.22.2, SEC-7.22.4."""

from core.evidence.media_validation import UnsupportedMediaError, verify_evidence_media
from tests.conftest import MINIMAL_JPEG_BYTES


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
