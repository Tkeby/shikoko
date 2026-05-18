"""Integration tests for shikoko.introspect.connection — real pool lifecycle.

Requires the ``shikoko-test-db`` container running on localhost:54323.
The test skips cleanly if the database is unreachable (no Docker, no Postgres).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shikoko.config import ConnectionSettings

try:
    from shikoko.introspect.connection import connect_pool, create_pool
except ImportError:
    pytest.skip("asyncpg not available", allow_module_level=True)

_DSN = "postgresql://shikoko:shikoko@localhost:54323/shikoko"


def _test_dsn() -> str | None:
    """Return a DSN suitable for testing, or None to skip."""
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or _DSN


@pytest.fixture
def dsn() -> str | None:
    return _test_dsn()


@pytest.fixture
def settings(dsn: str | None) -> ConnectionSettings | None:
    if dsn is None:
        return None
    from shikoko.config import _parse_dsn

    return _parse_dsn(dsn)


def _pg_unreachable() -> bool:
    """Check whether the test Postgres is available on port 54323."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        result = sock.connect_ex(("localhost", 54323))
        return result != 0
    finally:
        sock.close()


skip_no_pg = pytest.mark.skipif(
    _pg_unreachable() and not _test_dsn(),
    reason="Test Postgres not reachable on localhost:54323",
)


@skip_no_pg
async def test_create_pool_connects(settings: ConnectionSettings) -> None:
    if settings is None:
        settings = ConnectionSettings(
            host="localhost",
            port=54323,
            user="shikoko",
            password="shikoko",
            database="shikoko",
        )
    pool = await create_pool(settings)
    try:
        async with pool.acquire() as conn:
            val = await conn.fetchval("select 1")
            assert val == 1
    finally:
        await pool.close()


@skip_no_pg
async def test_connect_pool_context_manager(settings: ConnectionSettings) -> None:
    if settings is None:
        settings = ConnectionSettings(
            host="localhost",
            port=54323,
            user="shikoko",
            password="shikoko",
            database="shikoko",
        )
    async with connect_pool(settings) as pool:
        val = await pool.fetchval("select 42")
        assert val == 42


@skip_no_pg
async def test_generate_connects_and_exits(tmp_path: Path) -> None:
    """M1 acceptance: ``shikoko generate`` connects to a database and exits cleanly."""
    import subprocess
    import sys

    # Create a minimal sql/ directory so the generate command finds something.
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "dummy.sql").write_text("select 1 as val\n", encoding="utf-8")

    dsn = _test_dsn()
    cmd = [sys.executable, "-m", "shikoko", "generate", "--root", str(tmp_path)]
    cmd.extend(["--database-url", dsn or _DSN])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "Done." in result.stdout
