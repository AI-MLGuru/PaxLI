from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base


class RateLimitWindowRecord(Base):
    """Persistence for a single fixed-window counter (Foundation-010).

    (scope_key, window_start) is the primary key -- the exact pair the
    atomic upsert in infrastructure/rate_limit/postgres_limiter.py targets,
    so every admission check is a single INSERT ... ON CONFLICT DO UPDATE
    statement, never a select-then-update race. `window_start` is always
    computed server-side (Postgres's own now()), never from application-
    server time, so multiple API replicas never disagree about which window
    a request falls into.
    """

    __tablename__ = "rate_limit_windows"
    __table_args__ = (Index("ix_rate_limit_windows_window_start", "window_start"),)

    scope_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
