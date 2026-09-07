import logging
from collections.abc import Awaitable, Callable
from time import monotonic

from core.reliability.enums import ComponentOutcome
from core.reliability.models import DependencyHealth

logger = logging.getLogger(__name__)


async def check_dependency(
    component: str,
    check: Callable[[], Awaitable[None]],
    *,
    timeout_seconds: float = 2.0,
) -> DependencyHealth:
    started = monotonic()
    try:
        import asyncio

        await asyncio.wait_for(check(), timeout=timeout_seconds)
    except TimeoutError:
        logger.warning("dependency_health_timeout", extra={"component": component})
        return DependencyHealth(
            component, ComponentOutcome.TIMEOUT, started, (monotonic() - started) * 1000
        )
    except Exception as exception:
        logger.warning(
            "dependency_health_failed",
            extra={"component": component, "error": str(exception)},
        )
        return DependencyHealth(
            component,
            ComponentOutcome.UNAVAILABLE,
            started,
            (monotonic() - started) * 1000,
            str(exception)[:256],
        )
    return DependencyHealth(
        component, ComponentOutcome.SUCCESS, started, (monotonic() - started) * 1000
    )
