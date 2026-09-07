import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from core.reliability.enums import ComponentOutcome, FailureCategory
from core.reliability.models import ComponentResult, FailureReason
from core.reliability.policies import RetryPolicy

T = TypeVar("T")


async def execute_with_reliability(
    operation: Callable[[], Awaitable[T]],
    *,
    timeout_seconds: float,
    retry_policy: RetryPolicy,
    category: FailureCategory,
    timeout_code: str,
    unavailable_code: str,
    retryable_exceptions: tuple[type[Exception], ...] = (
        TimeoutError,
        ConnectionError,
        OSError,
    ),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    random_value: Callable[[], float] = random.random,
) -> ComponentResult:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    for attempt in range(1, retry_policy.max_attempts + 1):
        try:
            value = await asyncio.wait_for(operation(), timeout=timeout_seconds)
            return ComponentResult(
                ComponentOutcome.SUCCESS, evidence=value, attempts=attempt
            )
        except asyncio.TimeoutError:
            if attempt == retry_policy.max_attempts:
                return ComponentResult(
                    ComponentOutcome.TIMEOUT,
                    reason=FailureReason(
                        timeout_code,
                        category,
                        "Dependency operation timed out",
                        retryable=True,
                    ),
                    attempts=attempt,
                )
            delay = min(
                retry_policy.max_delay_seconds,
                retry_policy.base_delay_seconds * (2 ** (attempt - 1)),
            )
            delay *= 1 + retry_policy.jitter_ratio * random_value()
            await sleep(delay)
        except retryable_exceptions:
            if attempt == retry_policy.max_attempts:
                return ComponentResult(
                    ComponentOutcome.UNAVAILABLE,
                    reason=FailureReason(
                        unavailable_code,
                        category,
                        "Dependency operation is unavailable",
                        retryable=True,
                    ),
                    attempts=attempt,
                )
            delay = min(
                retry_policy.max_delay_seconds,
                retry_policy.base_delay_seconds * (2 ** (attempt - 1)),
            )
            delay *= 1 + retry_policy.jitter_ratio * random_value()
            await sleep(delay)
        except Exception as exception:
            return ComponentResult(
                ComponentOutcome.FAILED,
                reason=FailureReason(
                    "DEPENDENCY_NON_RETRYABLE_FAILURE",
                    category,
                    str(exception)[:512],
                    retryable=False,
                ),
                attempts=attempt,
            )

    raise AssertionError("retry loop must return")
