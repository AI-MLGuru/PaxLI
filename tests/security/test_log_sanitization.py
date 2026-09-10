"""Requirement traceability: REL-10.25.1.

Structured logging is a new surface area Foundation-006's sanitizer tests
never exercised (they covered audit metadata and API errors). This proves
the same sanitizer, applied as a structlog processor, catches leaks through
*this* path specifically.
"""

import io
import json

import structlog

from apps.api.averiq_api.config import Settings
from infrastructure.observability.logging import _sanitize_processor, configure_logging


def _configure_capturing_logger() -> io.StringIO:
    buffer = io.StringIO()
    configure_logging(Settings(log_level="INFO"))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _sanitize_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),
        logger_factory=structlog.PrintLoggerFactory(file=buffer),
        cache_logger_on_first_use=False,
    )
    return buffer


def test_canary_sensitive_values_never_appear_in_structured_log_output() -> None:
    buffer = _configure_capturing_logger()
    logger = structlog.get_logger("test")

    logger.info(
        "dependency_call",
        nin="CANARY_NIN_12345678901",
        bvn="CANARY_BVN_98765432109",
        document_number="CANARY_DOC_NUMBER",
        api_key="CANARY_API_KEY_VALUE",
        bearer_token="CANARY_BEARER_TOKEN",
        access_token="CANARY_ACCESS_TOKEN",
        password="CANARY_PASSWORD",
        embedding=[0.1, 0.2, "CANARY_EMBEDDING_MARKER"],
        selfie=b"CANARY_BIOMETRIC_BYTES",
        name="CANARY_FULL_NAME",
    )

    output = buffer.getvalue()
    for canary in (
        "CANARY_NIN_12345678901",
        "CANARY_BVN_98765432109",
        "CANARY_DOC_NUMBER",
        "CANARY_API_KEY_VALUE",
        "CANARY_BEARER_TOKEN",
        "CANARY_ACCESS_TOKEN",
        "CANARY_PASSWORD",
        "CANARY_EMBEDDING_MARKER",
        "CANARY_BIOMETRIC_BYTES",
        "CANARY_FULL_NAME",
    ):
        assert canary not in output, f"{canary} leaked into structured logs"


def test_operational_fields_survive_sanitization() -> None:
    buffer = _configure_capturing_logger()
    logger = structlog.get_logger("test")

    logger.info(
        "dependency_call",
        dependency="postgres",
        operation="commit",
        outcome="SUCCESS",
        attempts=1,
        duration_ms=12.3,
    )

    parsed = json.loads(buffer.getvalue())
    assert parsed["dependency"] == "postgres"
    assert parsed["operation"] == "commit"
    assert parsed["outcome"] == "SUCCESS"
    assert parsed["attempts"] == 1
    assert parsed["duration_ms"] == 12.3
