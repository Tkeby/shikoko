"""Shared fixtures for integration tests.

Requires the ``shikoko-test-db`` container from ``example/docker-compose.yml``
running on localhost:54323.
"""

from __future__ import annotations

from pathlib import Path

import asyncpg
import pytest

_DSN = "postgresql://shikoko:shikoko@localhost:54323/shikoko"
_FIXTURES = Path(__file__).parent / "fixtures"
_SCHEMAS = _FIXTURES / "schemas"
_QUERIES = _FIXTURES / "queries"


def _pg_reachable() -> bool:
    """Check if the test Postgres is reachable."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        result = sock.connect_ex(("localhost", 54323))
        return result == 0
    finally:
        sock.close()


skip_no_db = pytest.mark.skipif(
    not _pg_reachable(),
    reason="Test Postgres not reachable on localhost:54323",
)


@pytest.fixture
async def pool():
    """Provide a connection pool to the test database, closing after the test."""
    async with asyncpg.create_pool(_DSN, min_size=1, max_size=3) as p:
        yield p


@pytest.fixture
async def conn(pool: asyncpg.Pool):
    """Provide a single connection from the pool."""
    async with pool.acquire() as c:
        yield c


@pytest.fixture
async def schema_conn(conn: asyncpg.Connection):
    """Provide a connection with the test schema applied.

    Tears down (drops tables) first, then creates fresh, so the fixture
    is idempotent across runs even if the DB persists between test suites.
    """
    # Teardown first (reverse dependency order) in case tables linger.
    await conn.execute("drop table if exists posts")
    await conn.execute("drop table if exists users")
    await conn.execute("drop table if exists orgs")
    # Create fresh.
    for sql_file in sorted(_SCHEMAS.glob("*.sql")):
        await conn.execute(sql_file.read_text(encoding="utf-8"))
    yield conn
    # Teardown after the test too.
    await conn.execute("drop table if exists posts")
    await conn.execute("drop table if exists users")
    await conn.execute("drop table if exists orgs")


@pytest.fixture
def fixtures_dir() -> Path:
    return _FIXTURES


@pytest.fixture
def queries_dir() -> Path:
    return _QUERIES
