"""Operational verification-stage events (BD-001.17)."""

from typing import Literal

import structlog

Stage = Literal[
    "document_quality",
    "document_classification",
    "document_mrz",
    "document_barcode",
    "document_ocr",
    "document_field_extraction",
    "reference_acquisition",
    "face_detection_reference",
    "face_quality_reference",
    "face_embedding_reference",
    "face_detection_probe",
    "face_quality_probe",
    "face_embedding_probe",
    "face_match",
    "temporal_liveness_demo",
    "liveness_capture",
]
StageEvent = Literal[
    "verification_stage_started",
    "verification_stage_completed",
    "verification_stage_inconclusive",
    "verification_stage_unavailable",
    "verification_stage_failed",
]

logger = structlog.get_logger("paxli.verification_stage")


def log_stage_event(
    event: StageEvent,
    *,
    stage: Stage,
    request_id: str | None = None,
    correlation_id: str | None = None,
    session_id: str | None = None,
    duration_ms: float | None = None,
    attempt: int | None = None,
    evidence_result_id: str | None = None,
    model_id: str | None = None,
    model_version: str | None = None,
    failure_category: str | None = None,
    frame_count: int | None = None,
) -> None:
    """Emit one bounded operational event without affecting the caller.

    Callers pass operational metadata explicitly; payloads and arbitrary
    dictionaries are intentionally not accepted. Logging failures are
    swallowed so observability cannot alter pipeline behavior.
    """
    try:
        logger.info(
            event,
            stage=stage,
            request_id=request_id,
            correlation_id=correlation_id,
            session_id=session_id,
            duration_ms=round(duration_ms, 2) if duration_ms is not None else None,
            attempt=attempt,
            evidence_result_id=evidence_result_id,
            model_id=model_id,
            model_version=model_version,
            failure_category=failure_category,
            frame_count=frame_count,
        )
    except Exception:
        return
