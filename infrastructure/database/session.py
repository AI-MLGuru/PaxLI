from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.paxli_api.config import get_settings
from infrastructure.reliability.postgres_policies import guarded_commit

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Per-request unit of work.

    Repositories only `add()`/`flush()`; nothing they stage becomes durable
    until this single commit at the end of a successful request. This is
    what makes a governed effect and its required audit event durable
    together atomically: if anything in the request raises (including a
    required-audit failure), everything staged on this session is rolled
    back and no partial governed effect is ever externally observable.

    The commit itself goes through `guarded_commit`: bounded timeout, but
    deliberately never auto-retried (see infrastructure/reliability/
    postgres_policies.py) -- an uncertain COMMIT outcome must not be
    silently resubmitted by this layer.
    """
    async with session_factory() as session:
        try:
            yield session
            await guarded_commit(session)
        except Exception:
            await session.rollback()
            raise
