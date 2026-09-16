from typing import Any
from uuid import uuid4

import pytest
import structlog

from apps.api.paxli_api.config import Settings
from core.evidence_result.enums import EvidenceResultStatus
from infrastructure.observability.logging import configure_logging
from infrastructure.observability.stage_logging import log_stage_event


def test_rendered_stage_event_redacts_payload_canaries(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(Settings(log_level="INFO"))
    try:
        structlog.get_logger("paxli.test").info(
            "verification_stage_completed",
            stage="face_embedding_probe",
            ocr="OCR_CANARY_9f",
            nin="NIN_CANARY_7a",
            bvn="BVN_CANARY_3c",
            embedding="EMBEDDING_CANARY_2b",
            liveness_frame=b"LIVENESS_FRAME_CANARY_1d",
            raw_bytes=b"RAW_BYTES_CANARY_4e",
            nested_provider_response={
                "ocr_text": "NESTED_OCR_CANARY_5f",
                "face_embedding": "NESTED_EMBEDDING_CANARY_6a",
                "exception": ValueError("EXCEPTION_CANARY_7b"),
            },
            arbitrary_metadata={
                "document_number": "ARBITRARY_METADATA_CANARY_8c",
                "raw_bytes": b"ARBITRARY_BYTES_CANARY_9d",
            },
            session_id="session-123",
        )
        rendered = capsys.readouterr().out
    finally:
        structlog.reset_defaults()

    for canary in (
        "OCR_CANARY_9f",
        "NIN_CANARY_7a",
        "BVN_CANARY_3c",
        "EMBEDDING_CANARY_2b",
        "LIVENESS_FRAME_CANARY_1d",
        "RAW_BYTES_CANARY_4e",
        "NESTED_OCR_CANARY_5f",
        "NESTED_EMBEDDING_CANARY_6a",
        "EXCEPTION_CANARY_7b",
        "ARBITRARY_METADATA_CANARY_8c",
        "ARBITRARY_BYTES_CANARY_9d",
    ):
        assert canary not in rendered
    assert "session-123" in rendered


def test_stage_logging_swallows_logger_failure(monkeypatch: Any) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("logger failed")

    monkeypatch.setattr("infrastructure.observability.stage_logging.logger.info", fail)

    log_stage_event(
        "verification_stage_failed",
        stage="face_match",
        failure_category="provider_failed",
    )


def test_biometric_processor_stage_wrapper_logs_boundaries(monkeypatch: Any) -> None:
    seen: list[tuple[str, str]] = []

    def capture(event: str, **kwargs: Any) -> None:
        seen.append((event, kwargs["stage"]))

    monkeypatch.setattr("infrastructure.face.processor.log_stage_event", capture)
    from infrastructure.face.processor import BiometricProcessor

    processor = object.__new__(BiometricProcessor)

    class Result:
        status = EvidenceResultStatus.PASS
        id = uuid4()

    import asyncio

    asyncio.run(
        processor._run_observed_stage(
            "face_match",
            lambda: _completed_result(Result()),
            session_id=uuid4(),
            request_id="request-123",
            correlation_id="correlation-123",
        )
    )

    assert ("verification_stage_started", "face_match") in seen
    assert ("verification_stage_completed", "face_match") in seen


async def _completed_result(result: Any) -> Any:
    return result