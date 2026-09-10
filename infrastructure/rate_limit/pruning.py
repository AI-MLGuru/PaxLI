from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infrastructure.database.models.rate_limit_window import RateLimitWindowRecord


async def prune_expired_windows(
    session_factory: async_sessionmaker[AsyncSession], *, retention: timedelta
) -> int:
    """Storage hygiene only -- never load-bearing for admission correctness.
    check_and_consume() always computes window_start fresh (server-side)
    and upserts by the exact (scope_key, window_start) key, so a stale,
    unpruned row from a past window is simply irrelevant -- never read by
    any admission check. This function is safe to skip, delay, or fail
    without affecting a single admission decision (Foundation-010 review:
    "pruning is storage hygiene, not correctness")."""
    cutoff = datetime.now(UTC) - retention
    async with session_factory() as session:
        result = cast(
            "CursorResult[Any]",
            await session.execute(
                delete(RateLimitWindowRecord).where(RateLimitWindowRecord.window_start < cutoff)
            ),
        )
        await session.commit()
        return int(result.rowcount)
