"""Integration tests for the EXPLAIN runner (§4.1) and column-origins extractor (§4.2).

Requires the test Postgres running on localhost:54323.
"""

from __future__ import annotations

import socket

import pytest

from pysquirrel.introspect.plan import Plan, column_origins, run_explain


def _pg_reachable() -> bool:
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


@skip_no_db
async def test_explain_returns_plan(conn: object) -> None:
    """A simple ``select 1`` produces a non-null Plan with at least one node."""
    plan = await run_explain(conn, "select 1")  # type: ignore[arg-type]
    assert plan is not None
    assert isinstance(plan, Plan)
    assert len(plan.output) >= 1


@skip_no_db
async def test_explain_returns_none_for_do_block(conn: object) -> None:
    """``do $$ begin perform 1; end $$`` yields None, not an exception."""
    plan = await run_explain(conn, "do $$ begin perform 1; end $$")  # type: ignore[arg-type]
    assert plan is None


@skip_no_db
async def test_plan_carries_column_origins(schema_conn: object) -> None:
    """``select id, email from users`` yields (table_oid, attnum) matching pg_attribute.

    A computed column (``select count(*) from users``) yields (0, 0).
    """
    import asyncpg

    conn: asyncpg.Connection = schema_conn  # type: ignore[assignment]

    # --- base-table columns should resolve ---
    plan = await run_explain(conn, "select id, email from users")
    assert plan is not None
    origins = await column_origins(conn, plan, ncols=2)

    assert len(origins) == 2
    for (table_oid, attnum), col_name in zip(origins, ["id", "email"], strict=True):
        assert table_oid != 0, f"table_oid for {col_name} should not be 0"
        assert attnum > 0, f"attnum for {col_name} should be positive"

        row = await conn.fetchrow(
            "select attnotnull from pg_attribute where attrelid = $1 and attnum = $2",
            table_oid,
            attnum,
        )
        assert row is not None, f"pg_attribute row for {col_name} not found"

    # --- computed column should yield (0, 0) ---
    plan = await run_explain(conn, "select count(*) from users")
    assert plan is not None
    origins = await column_origins(conn, plan, ncols=1)
    assert origins == [(0, 0)]
