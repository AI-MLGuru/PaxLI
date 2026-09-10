"""Focused migration tests.

Runs the real Alembic CLI against the configured PostgreSQL database.
Skipped when that database isn't reachable (e.g. no local Postgres running),
since the rest of the suite deliberately runs against SQLite and doesn't
require Postgres.
"""

import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

from apps.api.averiq_api.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def _postgres_reachable() -> bool:
    url = urlparse(get_settings().database_url.replace("+asyncpg", ""))
    try:
        with socket.create_connection((url.hostname, url.port or 5432), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(), reason="PostgreSQL is not reachable in this environment"
)


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_upgrade_head_reaches_current_revision() -> None:
    upgrade = _run_alembic("upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    current = _run_alembic("current")
    assert current.returncode == 0, current.stderr
    assert "(head)" in current.stdout


def test_models_and_migrations_have_no_drift() -> None:
    """Alembic autogenerate against the live schema must find nothing new to
    add: proves the migration history matches the current SQLAlchemy models."""
    _run_alembic("upgrade", "head")
    check = _run_alembic("check")
    assert check.returncode == 0, check.stdout + check.stderr


def test_downgrade_to_base_and_back_upgrade_round_trips() -> None:
    """Proves the pre-Foundation-006 baseline -> current schema upgrade path
    (and its reverse) both execute cleanly."""
    down = _run_alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr

    baseline_only = _run_alembic("upgrade", "0041e99b1487")
    assert baseline_only.returncode == 0, baseline_only.stderr

    to_head = _run_alembic("upgrade", "head")
    assert to_head.returncode == 0, to_head.stderr

    current = _run_alembic("current")
    assert "(head)" in current.stdout
