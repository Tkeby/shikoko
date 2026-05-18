"""Integration tests for the prepare/introspection pipeline.

Requires the test Postgres running on localhost:54323.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pysquirrel.errors import IntrospectionError
from pysquirrel.introspect.prepare import build_query_ir, prepare_query
from pysquirrel.parser import ParsedQuery, parse_sql_file
from pysquirrel.types.oid_map import resolve_type


def _pg_reachable() -> bool:
    """Check if the test Postgres is reachable on port 54323."""
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


@skip_no_db
async def test_prepare_query_extracts_columns(
    schema_conn: object,
    queries_dir: Path,
) -> None:
    """prepare_query returns column metadata with correct names and type OIDs."""
    parsed = parse_sql_file(queries_dir / "find_user.sql")
    columns, _params = await prepare_query(schema_conn, parsed)  # type: ignore[arg-type]

    assert len(columns) == 3
    names = [c.name for c in columns]
    assert names == ["id", "email", "name"]

    oid_by_name = {c.name: c.type_oid for c in columns}
    assert oid_by_name["id"] == 23  # int4
    assert oid_by_name["email"] == 25  # text
    assert oid_by_name["name"] == 25  # text


@skip_no_db
async def test_prepare_query_extracts_params(
    schema_conn: object,
    queries_dir: Path,
) -> None:
    """prepare_query returns parameter metadata with correct OIDs."""
    parsed = parse_sql_file(queries_dir / "find_user.sql")
    _columns, params = await prepare_query(schema_conn, parsed)  # type: ignore[arg-type]

    assert len(params) == 1
    assert params[0].name == "_1"
    assert params[0].type_oid == 25  # text


@skip_no_db
async def test_build_query_ir_find_user(
    schema_conn: object,
    queries_dir: Path,
) -> None:
    """build_query_ir produces a correct QueryIR for a -- @one query."""
    from pysquirrel.codegen.ir import ReturnKind

    parsed = parse_sql_file(queries_dir / "find_user.sql")
    ir = await build_query_ir(schema_conn, parsed, resolve_type)  # type: ignore[arg-type]

    assert ir.name == "find_user"
    assert ir.return_kind == ReturnKind.ONE
    assert ir.row_model_name == "FindUserRow"
    assert len(ir.fields) == 3
    assert [f.name for f in ir.fields] == ["id", "email", "name"]
    assert len(ir.params) == 1
    assert ir.params[0].name == "_1"
    assert ir.params[0].py_type.annotation == "str"


@skip_no_db
async def test_build_query_ir_list_users(
    schema_conn: object,
    queries_dir: Path,
) -> None:
    """build_query_ir produces a correct QueryIR for a default (MANY) query."""
    from pysquirrel.codegen.ir import ReturnKind

    parsed = parse_sql_file(queries_dir / "list_users.sql")
    ir = await build_query_ir(schema_conn, parsed, resolve_type)  # type: ignore[arg-type]

    assert ir.name == "list_users"
    assert ir.return_kind == ReturnKind.MANY
    assert ir.row_model_name == "ListUsersRow"
    assert len(ir.fields) == 3
    assert len(ir.params) == 0


@skip_no_db
async def test_build_query_ir_create_user(
    schema_conn: object,
    queries_dir: Path,
) -> None:
    """build_query_ir produces a correct QueryIR for an -- @exec query."""
    from pysquirrel.codegen.ir import ReturnKind

    parsed = parse_sql_file(queries_dir / "create_user.sql")
    ir = await build_query_ir(schema_conn, parsed, resolve_type)  # type: ignore[arg-type]

    assert ir.name == "create_user"
    assert ir.return_kind == ReturnKind.EXEC
    assert ir.row_model_name == ""
    assert len(ir.fields) == 0
    assert len(ir.params) == 2
    assert ir.params[0].py_type.annotation == "str"
    assert ir.params[1].py_type.annotation == "str"


@skip_no_db
async def test_prepare_invalid_sql_raises(
    schema_conn: object,
) -> None:
    """prepare_query raises IntrospectionError for invalid SQL."""
    parsed = ParsedQuery(
        name="bad",
        doc="",
        body="select from",
        source_file=Path("bad.sql"),
        source_line=1,
    )
    with pytest.raises(IntrospectionError):
        await prepare_query(schema_conn, parsed)  # type: ignore[arg-type]
