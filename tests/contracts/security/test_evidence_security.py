"""Requirement traceability: SEC-7.14.2, SEC-7.16.*, SEC-7.17.5, SEC-7.22.2, PRV-11.6.*, 11.23.*."""

from tests.conftest import MINIMAL_JPEG_BYTES


def test_uploaded_selfie_is_encrypted_before_reaching_storage(
    api_client, issued_credentials, raw_storage
) -> None:
    """PRV-11.23.1 / SEC-7.14.2: highly sensitive evidence must not be persisted
    as plaintext in object storage."""
    create_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    session_id = create_response.json()["data"]["id"]

    plaintext = MINIMAL_JPEG_BYTES + b"CANARY_RAW_SELFIE_BYTES_SHOULD_NEVER_BE_STORED_VERBATIM"
    upload_response = api_client.post(
        f"/v1/verification-sessions/{session_id}/selfie",
        files={"file": ("selfie.jpg", plaintext, "image/jpeg")},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert upload_response.status_code == 201

    assert len(raw_storage.blobs) == 1
    stored_bytes = next(iter(raw_storage.blobs.values()))
    assert plaintext not in stored_bytes
    assert stored_bytes != plaintext


def test_evidence_response_never_includes_raw_content(api_client, issued_credentials) -> None:
    """SEC-7.16.6 / PRV-11.7.3: evidence responses expose metadata only."""
    create_response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    session_id = create_response.json()["data"]["id"]

    upload_response = api_client.post(
        f"/v1/verification-sessions/{session_id}/document",
        files={"file": ("doc.jpg", MINIMAL_JPEG_BYTES + b"CANARY_DOCUMENT_BYTES", "image/jpeg")},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert upload_response.status_code == 201
    body = upload_response.json()
    assert set(body.keys()) == {
        "id",
        "session_id",
        "evidence_type",
        "source",
        "checksum",
        "mime_type",
        "size_bytes",
        "metadata",
        "created_at",
        "retention_until",
    }
