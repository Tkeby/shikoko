"""asyncpg connection helpers — pool lifecycle and server version gate."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg

from shikoko.config import ConnectionSettings
from shikoko.errors import IntrospectionError

logger = logging.getLogger(__name__)

_MIN_SERVER_VERSION = 160000  # PostgreSQL 16+


async def create_pool(
    settings: ConnectionSettings,
) -> asyncpg.Pool:
    """Open an ``asyncpg`` pool and verify the server is PostgreSQL >= 16.

    Raises :class:`IntrospectionError` when the server version is too old or
    the connection cannot be established.
    """
    try:
        pool = await asyncpg.create_pool(
            dsn=settings.dsn,
            min_size=1,
            max_size=5,
        )
    except Exception as exc:
        raise IntrospectionError(
            file=Path(__file__),
            message=f"could not connect to {settings.host}:{settings.port}/{settings.database}: {exc}",
        ) from exc

    async with pool.acquire() as conn:
        version_num = await conn.fetchval(
            "select current_setting('server_version_num')"
        )
        version_num = int(version_num)
        if version_num < _MIN_SERVER_VERSION:
            await pool.close()
            major = version_num // 10000
            raise IntrospectionError(
                file=Path(__file__),
                message=(
                    f"PostgreSQL {major} is not supported; "
                    f"shikoko requires PostgreSQL 16 or later "
                    f"(server_version_num={version_num})"
                ),
            )

    logger.info(
        "connected to %s:%s/%s (server_version_num=%s)",
        settings.host,
        settings.port,
        settings.database,
        version_num,
    )
    return pool


@asynccontextmanager
async def connect_pool(
    settings: ConnectionSettings,
) -> AsyncIterator[asyncpg.Pool]:
    """Context manager that opens a pool, yields it, then closes on exit."""
    pool = await create_pool(settings)
    try:
        yield pool
    finally:
        await pool.close()
