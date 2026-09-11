"""MinIO reliability policies (REL-10.8, REL-10.9, REL-10.10).

GET and DELETE are safe to retry unconditionally: GET is a pure read, and
the existing `MinioObjectStorage.delete()` already treats deleting an
already-deleted key as a no-op (it swallows `S3Error`), so a retried delete
cannot fail differently than the first attempt.

PUT is retryable specifically because of three properties that hold
together in PaxLI's design, not because "S3 PUT is generally idempotent":
  1. the object key is content-addressed (SHA-256 of the plaintext,
     computed before encryption), so retrying with the same input produces
     the same key;
  2. PUT-to-an-existing-key is a full replace, never an append or merge;
  3. AES-GCM uses a fresh random nonce per encryption, so a retried PUT
     writes different ciphertext bytes than the first attempt -- but both
     decrypt to the identical plaintext, which is what correctness actually
     depends on (verified independently via the stored SHA-256 checksum).
If a future change makes object keys non-deterministic, or introduces a
storage backend where PUT is not a full replace, this retry guarantee must
be re-evaluated.
"""

from collections.abc import Awaitable, Callable

from core.reliability.circuit_breaker import CircuitBreaker
from core.reliability.metrics import ReliabilityMetrics
from core.reliability.policies import RetryPolicy
from infrastructure.reliability._shared import run_guarded

METRICS = ReliabilityMetrics()
BREAKER = CircuitBreaker(failure_threshold=5, recovery_timeout_seconds=30.0, metrics=METRICS)

GET_TIMEOUT_SECONDS = 10.0
GET_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay_seconds=0.2, max_delay_seconds=2.0)

PUT_TIMEOUT_SECONDS = 30.0
PUT_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay_seconds=0.2, max_delay_seconds=2.0)

DELETE_TIMEOUT_SECONDS = 10.0
DELETE_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay_seconds=0.2, max_delay_seconds=2.0)


class MinioOperationError(RuntimeError):
    """A guarded MinIO operation did not complete after bounded retry."""


async def guarded_get[T](operation: Callable[[], Awaitable[T]]) -> T:
    result = await run_guarded(
        operation,
        dependency="minio",
        operation_name="get",
        timeout_seconds=GET_TIMEOUT_SECONDS,
        retry_policy=GET_RETRY_POLICY,
        breaker=BREAKER,
        metrics=METRICS,
    )
    if not result.successful:
        message = result.reason.message if result.reason else "get did not complete"
        raise MinioOperationError(message)
    return result.evidence  # type: ignore[return-value]


async def guarded_put(operation: Callable[[], Awaitable[None]]) -> None:
    result = await run_guarded(
        operation,
        dependency="minio",
        operation_name="put",
        timeout_seconds=PUT_TIMEOUT_SECONDS,
        retry_policy=PUT_RETRY_POLICY,
        breaker=BREAKER,
        metrics=METRICS,
    )
    if not result.successful:
        message = result.reason.message if result.reason else "put did not complete"
        raise MinioOperationError(message)


async def guarded_delete(operation: Callable[[], Awaitable[None]]) -> None:
    result = await run_guarded(
        operation,
        dependency="minio",
        operation_name="delete",
        timeout_seconds=DELETE_TIMEOUT_SECONDS,
        retry_policy=DELETE_RETRY_POLICY,
        breaker=BREAKER,
        metrics=METRICS,
    )
    if not result.successful:
        message = result.reason.message if result.reason else "delete did not complete"
        raise MinioOperationError(message)
