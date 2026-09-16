from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import StrEnum
from re import sub
from typing import Any
from uuid import UUID


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    HIGHLY_SENSITIVE = "highly_sensitive"


REDACTED_SENSITIVE = "[REDACTED:SENSITIVE]"
REDACTED_HIGHLY_SENSITIVE = "[REDACTED:HIGHLY_SENSITIVE]"
REDACTED_BINARY = "[REDACTED:BINARY]"
REDACTED_UNSERIALIZABLE = "[REDACTED:UNSERIALIZABLE]"

SENSITIVE_FIELDS = frozenset(
    {
        "name",
        "full_name",
        "date_of_birth",
        "dob",
        "address",
        "phone",
        "phone_number",
        "email",
        "document_number",
        "document_type",
        "nationality",
        "nin",
        "bvn",
        "verification_id",
        "verification_identifier",
        "ocr",
        "raw_text",
        "ocr_text",
    }
)

HIGHLY_SENSITIVE_FIELDS = frozenset(
    {
        "authorization",
        "cookie",
        "document",
        "image",
        "selfie",
        "document_image",
        "raw_document_payload",
        "liveness_image",
        "liveness_video",
        "embedding",
        "face_embedding",
        "biometric_template",
        "access_token",
        "refresh_token",
        "bearer_token",
        "api_key",
        "client_secret",
        "password",
        "password_hash",
        "private_key",
        "secret",
        "token",
    }
)

HIGHLY_SENSITIVE_FIELD_PARTS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "bearer_token",
        "client_secret",
        "cookie",
        "embedding",
        "image",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "token",
    }
)

_MAX_STRING_LENGTH = 512
_MAX_ITEMS = 50


def _normalize_field_name(field_name: str) -> str:
    snake_case = sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", field_name.strip())
    return snake_case.lower().replace("-", "_").replace(" ", "_")


def classify_field(field_name: str | None) -> DataClassification:
    if field_name is None:
        return DataClassification.INTERNAL
    normalized = _normalize_field_name(field_name)
    if normalized in HIGHLY_SENSITIVE_FIELDS or normalized in HIGHLY_SENSITIVE_FIELD_PARTS:
        return DataClassification.HIGHLY_SENSITIVE
    if normalized in SENSITIVE_FIELDS or normalized.endswith(
        ("_email", "_phone", "_document_number", "_date_of_birth")
    ):
        return DataClassification.SENSITIVE
    return DataClassification.INTERNAL


def _redaction_for(classification: DataClassification) -> str:
    if classification == DataClassification.HIGHLY_SENSITIVE:
        return REDACTED_HIGHLY_SENSITIVE
    return REDACTED_SENSITIVE


def sanitize_value(
    value: Any,
    *,
    field_name: str | None = None,
    _ancestors: frozenset[int] = frozenset(),
    _depth: int = 0,
) -> Any:
    classification = classify_field(field_name)
    is_structured_document = _normalize_field_name(field_name or "") == "document" and isinstance(
        value, Mapping
    )
    if (
        classification
        in {
            DataClassification.SENSITIVE,
            DataClassification.HIGHLY_SENSITIVE,
        }
        and not is_structured_document
    ):
        return _redaction_for(classification)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return REDACTED_BINARY
    if _depth >= 20 or id(value) in _ancestors:
        return REDACTED_UNSERIALIZABLE
    if isinstance(value, Mapping):
        ancestors = _ancestors | {id(value)}
        return {
            str(key): sanitize_value(
                item, field_name=str(key), _ancestors=ancestors, _depth=_depth + 1
            )
            for key, item in list(value.items())[:_MAX_ITEMS]
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        ancestors = _ancestors | {id(value)}
        return [
            sanitize_value(item, _ancestors=ancestors, _depth=_depth + 1)
            for item in list(value)[:_MAX_ITEMS]
        ]
    if isinstance(value, str):
        return value[:_MAX_STRING_LENGTH]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (datetime, date, UUID, StrEnum)):
        return str(value)
    return REDACTED_UNSERIALIZABLE


def sanitize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_value(metadata)
    return sanitized if isinstance(sanitized, dict) else {}


def safe_exception_message(_: BaseException, *, fallback: str = "Operation failed") -> str:
    return fallback
