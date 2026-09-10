"""PostgreSQL reliability policies (REL-10.8, REL-10.9, REL-10.10).

Only one call site is wrapped: COMMIT, via `guarded_commit`. This is
deliberate, not an oversight -- see the module docstring on the reasoning.

Connection acquisition and read queries are architecturally SAFE_TO_RETRY
(no durable state exists before COMMIT), but this pass does not retrofit
retry onto every repository's individual query methods -- that would touch
five-plus files well beyond this foundation's approved scope. The one read
call site this foundation does own -- the /ready dependency check -- uses
`core/reliability/health.check_dependency()` directly instead: a health
probe should NOT retry (REL-10.11.3, avoid harmful load on an already
possibly-struggling dependency), so it deliberately does not go through the
retry-capable policy below.

COMMIT is bounded by timeout but is NEVER auto-retried
(RetryPolicy(max_attempts=1)): a client cannot safely resubmit a COMMIT
whose acknowledgment was lost without an operation-specific idempotency
mechanism (Idempotency-Key / dedupe_key), and this module has no way to
know whether the specific write being committed has one. Retry-after-
uncertain-commit is a decision that belongs to the calling operation, not
to this reliability layer.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from core.reliability.circuit_breaker import CircuitBreaker
from core.reliability.metrics import ReliabilityMetrics
from core.reliability.policies import RetryPolicy
from infrastructure.reliability._shared import run_guarded

METRICS = ReliabilityMetrics()
BREAKER = CircuitBreaker(failure_threshold=5, recovery_timeout_seconds=30.0, metrics=METRICS)

COMMIT_TIMEOUT_SECONDS = 5.0
# max_attempts=1: bounded timeout, zero automatic retry. See module docstring.
COMMIT_RETRY_POLICY = RetryPolicy(max_attempts=1)


class PostgresOperationError(RuntimeError):
    """A guarded PostgreSQL operation did not complete safely.

    Covers both a definite failure (e.g. a constraint violation) and a
    genuinely uncertain outcome (timeout or connection loss during COMMIT).
    Callers MUST NOT assume the underlying write did not happen.
    """


async def guarded_commit(session: AsyncSession) -> None:
    result = await run_guarded(
        session.commit,
        dependency="postgres",
        operation_name="commit",
        timeout_seconds=COMMIT_TIMEOUT_SECONDS,
        retry_policy=COMMIT_RETRY_POLICY,
        breaker=BREAKER,
        metrics=METRICS,
    )
    if not result.successful:
        message = result.reason.message if result.reason else "commit did not complete safely"
        raise PostgresOperationError(message)
