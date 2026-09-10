from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.averiq_api.config import get_settings

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
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
