"""M2 acceptance tests: end-to-end pipeline from SQL → generated Python → execution.

Requires the test Postgres running on localhost:54323.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import asyncpg
import pytest

from shikoko.codegen.format import format_source
from shikoko.codegen.render import render_module
from shikoko.discovery import find_sql_files
from shikoko.introspect.prepare import build_query_ir
from shikoko.parser import parse_sql_file
from shikoko.types.oid_map import resolve_type


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

_SCHEMA_SQL = """\
drop table if exists posts;
drop table if exists users;
create table users (
    id    serial primary key,
    email text not null,
    name  text
);
create table posts (
    id       serial primary key,
    user_id  int not null references users(id),
    title    text not null,
    body     text
);
"""


async def _run_pipeline(root: Path, conn: asyncpg.Connection) -> Path:
    """Run the full generate pipeline against *root* and return the output path."""
    sql_files = find_sql_files(root)
    assert sql_files, "no .sql files found"

    # Group by sql/ directory (there should be exactly one in these tests).
    from collections import defaultdict

    by_dir: dict[Path, list[Path]] = defaultdict(list)
    for sql_dir, fpath in sql_files:
        by_dir[sql_dir].append(fpath)

    output_paths: list[Path] = []
    for sql_dir, files in sorted(by_dir.items()):
        queries_ir = []
        for fpath in sorted(files):
            parsed = parse_sql_file(fpath)
            ir = await build_query_ir(conn, parsed, resolve_type)
            queries_ir.append(ir)

        source_label = str(sql_dir.relative_to(root))
        source = render_module(queries_ir, source_label)
        source = await format_source(source)

        output_path = sql_dir.parent / "sql_generated.py"
        output_path.write_text(source, encoding="utf-8")
        output_paths.append(output_path)

    assert len(output_paths) == 1
    return output_paths[0]


def _import_generated(path: Path):
    """Dynamically import the generated module at *path*."""
    spec = importlib.util.spec_from_file_location("sql_generated", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@skip_no_db
async def test_generate_end_to_end(
    tmp_path: Path,
    conn: asyncpg.Connection,
) -> None:
    """A single SQL file produces a working Python module end-to-end."""
    # 1. Create a temp project with a SQL file.
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "find_user_by_id.sql").write_text(
        "-- Find user by ID.\n-- @one\nselect id, email, name from users where id = $1\n",
        encoding="utf-8",
    )

    # 2. Set up the schema.
    await conn.execute(_SCHEMA_SQL)

    try:
        # 3. Run the pipeline.
        generated_path = await _run_pipeline(tmp_path, conn)

        # 4. Assert file was written.
        assert generated_path.exists()
        source = generated_path.read_text(encoding="utf-8")

        # 5. Assert generated content has expected symbols.
        assert "class FindUserByIdRow" in source
        assert "async def find_user_by_id" in source

        # 6. Dynamic import and execution.
        mod = _import_generated(generated_path)

        # Insert a test row.
        row_id = await conn.fetchval(
            "insert into users (email, name) values ($1, $2) returning id",
            "alice@example.com",
            "Alice",
        )

        # Call the generated function.
        result = await mod.find_user_by_id(conn, row_id)
        assert result is not None
        assert result.id == row_id
        assert result.email == "alice@example.com"
        assert result.name == "Alice"

    finally:
        await conn.execute("drop table if exists posts")
        await conn.execute("drop table if exists users")


@skip_no_db
async def test_generate_multiple_queries(
    tmp_path: Path,
    conn: asyncpg.Connection,
) -> None:
    """Multiple .sql files produce a single module with all queries."""
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()

    (sql_dir / "find_user.sql").write_text(
        "-- Find a user.\n-- @one\nselect id, email, name from users where email = $1\n",
        encoding="utf-8",
    )
    (sql_dir / "list_users.sql").write_text(
        "-- List all users.\nselect id, email, name from users order by id\n",
        encoding="utf-8",
    )
    (sql_dir / "create_user.sql").write_text(
        "-- Create a user.\n-- @exec\ninsert into users (email, name) values ($1, $2)\n",
        encoding="utf-8",
    )

    await conn.execute(_SCHEMA_SQL)

    try:
        generated_path = await _run_pipeline(tmp_path, conn)
        source = generated_path.read_text(encoding="utf-8")

        # All three row models should be present (EXEC has no model).
        assert "class FindUserRow" in source
        assert "class ListUsersRow" in source

        # All three functions should be present.
        assert "async def find_user" in source
        assert "async def list_users" in source
        assert "async def create_user" in source

        # Verify it imports correctly.
        mod = _import_generated(generated_path)
        assert hasattr(mod, "find_user")
        assert hasattr(mod, "list_users")
        assert hasattr(mod, "create_user")

    finally:
        await conn.execute("drop table if exists posts")
        await conn.execute("drop table if exists users")


@skip_no_db
async def test_generated_code_executes(
    tmp_path: Path,
    conn: asyncpg.Connection,
) -> None:
    """Generate code for create_user + find_user, then execute the full data flow."""
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()

    (sql_dir / "create_user.sql").write_text(
        "-- Create a user.\n-- @exec\ninsert into users (email, name) values ($1, $2)\n",
        encoding="utf-8",
    )
    (sql_dir / "find_user.sql").write_text(
        "-- Find a user.\n-- @one\nselect id, email, name from users where email = $1\n",
        encoding="utf-8",
    )

    await conn.execute(_SCHEMA_SQL)

    try:
        generated_path = await _run_pipeline(tmp_path, conn)
        mod = _import_generated(generated_path)

        # Execute create_user.
        await mod.create_user(conn, "bob@example.com", "Bob")

        # Execute find_user to retrieve the row we just inserted.
        result = await mod.find_user(conn, "bob@example.com")
        assert result is not None
        assert result.email == "bob@example.com"
        assert result.name == "Bob"
        assert isinstance(result.id, int)

    finally:
        await conn.execute("drop table if exists posts")
        await conn.execute("drop table if exists users")
