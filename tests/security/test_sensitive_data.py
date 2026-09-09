import json
from datetime import UTC, datetime

from core.security.classification import (
    REDACTED_BINARY,
    REDACTED_HIGHLY_SENSITIVE,
    REDACTED_SENSITIVE,
    DataClassification,
    classify_field,
    safe_exception_message,
    sanitize_metadata,
)


def test_classification_is_case_insensitive_and_explicit() -> None:
    assert classify_field("Document_Number") == DataClassification.SENSITIVE
    assert classify_field("DOCUMENT_NUMBER") == DataClassification.SENSITIVE
    assert classify_field("face-embedding") == DataClassification.HIGHLY_SENSITIVE
    assert classify_field("accessToken") == DataClassification.HIGHLY_SENSITIVE
    assert classify_field("password_hash") == DataClassification.HIGHLY_SENSITIVE
    assert classify_field("image") == DataClassification.HIGHLY_SENSITIVE
    assert classify_field("cookie") == DataClassification.HIGHLY_SENSITIVE
    assert classify_field("contact_email") == DataClassification.SENSITIVE
    assert classify_field("request_id") == DataClassification.INTERNAL


def test_recursive_sanitization_redacts_pii_biometrics_and_secrets() -> None:
    metadata = {
        "name": "CANARY_NAME",
        "dob": "CANARY_DOB",
        "document_type": "national_id",
        "verification": {
            "document": {"document_number": "CANARY_NIN_123456789"},
            "face_embedding": ["CANARY_EMBEDDING"],
        },
        "documents": [
            {"document_number": "CANARY_DOCUMENT_1"},
            {"document_number": "CANARY_DOCUMENT_2"},
        ],
        "authorization": "CANARY_TOKEN",
        "cookie": "CANARY_COOKIE",
        "password_hash": "CANARY_PASSWORD_HASH",
        "image": "CANARY_IMAGE",
        "api_key": "CANARY_API_SECRET",
        "selfie": "CANARY_DOCUMENT_IMAGE",
    }

    sanitized = sanitize_metadata(metadata)
    serialized = json.dumps(sanitized)

    assert sanitized["name"] == REDACTED_SENSITIVE
    assert sanitized["dob"] == REDACTED_SENSITIVE
    assert sanitized["document_type"] == REDACTED_SENSITIVE
    assert sanitized["verification"]["document"]["document_number"] == REDACTED_SENSITIVE
    assert sanitized["verification"]["face_embedding"] == REDACTED_HIGHLY_SENSITIVE
    assert all(item["document_number"] == REDACTED_SENSITIVE for item in sanitized["documents"])
    assert sanitized["authorization"] == REDACTED_HIGHLY_SENSITIVE
    assert sanitized["api_key"] == REDACTED_HIGHLY_SENSITIVE
    assert sanitized["selfie"] == REDACTED_HIGHLY_SENSITIVE
    assert all(
        canary not in serialized
        for canary in (
            "CANARY_NIN_123456789",
            "CANARY_EMBEDDING",
            "CANARY_API_SECRET",
            "CANARY_DOCUMENT_IMAGE",
            "CANARY_TOKEN",
            "CANARY_COOKIE",
            "CANARY_PASSWORD_HASH",
            "CANARY_IMAGE",
        )
    )


def test_binary_and_unserializable_values_never_become_log_text() -> None:
    class SecretObject:
        def __str__(self) -> str:
            return "CANARY_OBJECT_SECRET"

    sanitized = sanitize_metadata(
        {
            "raw_bytes": b"CANARY_BYTES",
            "raw_bytearray": bytearray(b"CANARY_BYTEARRAY"),
            "raw_memoryview": memoryview(b"CANARY_MEMORYVIEW"),
            "unknown": SecretObject(),
        }
    )

    assert sanitized["raw_bytes"] == REDACTED_BINARY
    assert sanitized["raw_bytearray"] == REDACTED_BINARY
    assert sanitized["raw_memoryview"] == REDACTED_BINARY
    assert sanitized["unknown"] == "[REDACTED:UNSERIALIZABLE]"
    assert "CANARY" not in json.dumps(sanitized)


def test_cycles_are_bounded_and_common_operational_types_survive() -> None:
    cyclic: dict[str, object] = {"request_id": "req_123"}
    cyclic["self"] = cyclic

    sanitized = sanitize_metadata(
        {"cyclic": cyclic, "occurred_at": datetime(2026, 1, 1, tzinfo=UTC)}
    )

    assert sanitized["cyclic"]["self"] == "[REDACTED:UNSERIALIZABLE]"
    assert sanitized["occurred_at"] == "2026-01-01 00:00:00+00:00"


def test_operational_metadata_survives_and_exception_text_is_generic() -> None:
    sanitized = sanitize_metadata(
        {
            "request_id": "req_123",
            "component": "face_engine",
            "latency_ms": 184,
            "retry_count": 1,
        }
    )

    assert sanitized == {
        "request_id": "req_123",
        "component": "face_engine",
        "latency_ms": 184,
        "retry_count": 1,
    }
    error = ValueError("CANARY_NIN_123456789 and CANARY_API_SECRET")
    assert "CANARY" not in safe_exception_message(error, fallback="Operation failed")
    assert safe_exception_message(error, fallback="Operation failed") == "Operation failed"
