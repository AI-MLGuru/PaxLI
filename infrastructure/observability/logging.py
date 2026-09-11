"""Structured logging configuration (REL-10.25).

Configures structlog once at startup, reading `Settings.log_level` (which
existed but was never consumed before this). Every log event passes through
the same sensitive-data sanitizer already proven for audit metadata and API
errors (core/security/classification.sanitize_metadata), so a logging call
cannot become a new leakage path for identity numbers, credentials, or
biometric content.
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

from apps.api.paxli_api.config import Settings
from core.security.classification import sanitize_metadata


def _sanitize_processor(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    sanitized: dict[str, Any] = sanitize_metadata(event_dict)
    return sanitized


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s")

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _sanitize_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
