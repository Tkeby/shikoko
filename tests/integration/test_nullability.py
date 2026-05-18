"""Integration tests for nullability inference through the full pipeline.

Each test runs the full ``prepare → infer_nullability → render`` pipeline
against the test Postgres and asserts the generated RowModel fields carry
the correct ``T`` vs ``T | None`` annotations.

Requires the test Postgres running on localhost:54323.
"""

from __future__ import annotations

import socket
from pathlib import Path

import asyncpg
import pytest

from pysquirrel.introspect.catalog import CatalogCache
from pysquirrel.introspect.prepare import TypeResolver, build_query_ir
from pysquirrel.parser import parse_sql_file
from pysquirrel.types.oid_map import resolve_type


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

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "queries" / "nullability"


# ---------------------------------------------------------------------------
# Helper: run the full pipeline and return {field_name: annotation}
# ---------------------------------------------------------------------------


async def _annotate(conn: asyncpg.Connection, sql: str) -> dict[str, str]:
    """Run the full nullability pipeline on *sql* and return field annotations.

    This mirrors what ``build_query_ir`` does internally: prepare the
    statement, run EXPLAIN, extract column origins, run the inference,
    and return the cleaned field names mapped to their type annotation
    strings (``"int"``, ``"str | None"``, etc.).
    """
    from pysquirrel.parser import ParsedQuery

    parsed = ParsedQuery(
        name="test_query",
        doc="",
        body=sql,
        source_file=Path("<test>"),
        source_line=1,
    )
    ir = await build_query_ir(conn, parsed, resolve_type)
    return {
        f.name: (
            f.py_type.annotation if not f.nullable else f"{f.py_type.annotation} | None"
        )
        for f in ir.fields
    }


async def _annotate_with_resolver(conn: asyncpg.Connection, sql: str) -> dict[str, str]:
    """Like ``_annotate`` but uses a ``TypeResolver`` (the real pipeline path)."""
    from pysquirrel.parser import ParsedQuery

    parsed = ParsedQuery(
        name="test_query",
        doc="",
        body=sql,
        source_file=Path("<test>"),
        source_line=1,
    )
    catalog = CatalogCache(conn)
    resolver = TypeResolver(catalog)
    ir = await build_query_ir(conn, parsed, resolver)
    return {
        f.name: (
            f.py_type.annotation if not f.nullable else f"{f.py_type.annotation} | None"
        )
        for f in ir.fields
    }


# ---------------------------------------------------------------------------
# Headline acceptance test
# ---------------------------------------------------------------------------


@skip_no_db
async def test_left_join_right_side_nullable_no_overrides(
    schema_conn: asyncpg.Connection,
) -> None:
    """The exit-criteria smoke test."""
    sql = (
        "select u.id, o.name as org_name "
        "from users u left join orgs o on o.id = u.org_id"
    )
    fields = await _annotate(schema_conn, sql)
    assert fields == {"id": "int", "org_name": "str | None"}


# ---------------------------------------------------------------------------
# Join shape tests via the full pipeline
# ---------------------------------------------------------------------------


@skip_no_db
async def test_inner_join_both_sides_non_null(
    schema_conn: asyncpg.Connection,
) -> None:
    """Inner join: both sides come from catalog NOT NULL → non-null."""
    sql = "select u.id, o.name as org_name from users u join orgs o on o.id = u.org_id"
    fields = await _annotate(schema_conn, sql)
    assert fields["id"] == "int"
    assert fields["org_name"] == "str"


@skip_no_db
async def test_right_join_left_side_nullable(
    schema_conn: asyncpg.Connection,
) -> None:
    """Right join: left-side columns are nullable."""
    sql = (
        "select u.id, o.name as org_name "
        "from users u right join orgs o on o.id = u.org_id"
    )
    fields = await _annotate(schema_conn, sql)
    assert fields["id"] == "int | None"
    assert fields["org_name"] == "str"


@skip_no_db
async def test_full_join_both_sides_nullable(
    schema_conn: asyncpg.Connection,
) -> None:
    """Full join: both sides are nullable."""
    sql = (
        "select u.id, o.name as org_name "
        "from users u full join orgs o on o.id = u.org_id"
    )
    fields = await _annotate(schema_conn, sql)
    assert fields["id"] == "int | None"
    assert fields["org_name"] == "str | None"


# ---------------------------------------------------------------------------
# Catalog fallback (no join)
# ---------------------------------------------------------------------------


@skip_no_db
async def test_no_join_catalog_fallback(
    schema_conn: asyncpg.Connection,
) -> None:
    """No join: NOT NULL columns from catalog are non-null, nullable ones aren't."""
    sql = "select id, email, name from users"
    fields = await _annotate(schema_conn, sql)
    assert fields["id"] == "int"  # serial primary key → NOT NULL
    assert fields["email"] == "str"  # text NOT NULL
    assert fields["name"] == "str | None"  # text (nullable)


# ---------------------------------------------------------------------------
# Computed expression (no origin → nullable)
# ---------------------------------------------------------------------------


@skip_no_db
async def test_computed_expression_nullable(
    schema_conn: asyncpg.Connection,
) -> None:
    """Computed expression (count(*)) has no origin → defaults to nullable."""
    sql = "select count(*) as total from users"
    fields = await _annotate(schema_conn, sql)
    assert fields["total"] == "int | None"


# ---------------------------------------------------------------------------
# Override pathways
# ---------------------------------------------------------------------------


@skip_no_db
async def test_override_bang_forces_non_null(
    schema_conn: asyncpg.Connection,
) -> None:
    """Trailing ``!`` on a column alias forces non-null."""
    sql = "select u.id, u.org_id as org_id! from users u left join orgs o on o.id = u.org_id"
    fields = await _annotate(schema_conn, sql)
    assert fields["org_id"] == "int"  # forced non-null by !


# ---------------------------------------------------------------------------
# Day 4 — override end-to-end + edge cases
# ---------------------------------------------------------------------------


@skip_no_db
async def test_override_bang_with_left_join(
    schema_conn: asyncpg.Connection,
) -> None:
    """``created_at!`` is forced non-null; ``org_name`` is nullable from the left join."""
    sql = (
        "select u.created_at!, o.name as org_name "
        "from users u left join orgs o on o.id = u.org_id"
    )
    fields = await _annotate_with_resolver(schema_conn, sql)
    assert fields == {"created_at": "datetime", "org_name": "str | None"}


@skip_no_db
async def test_override_qmark_on_coalesce(
    schema_conn: asyncpg.Connection,
) -> None:
    """``coalesce(name, 'anon') as name?`` is nullable despite coalesce being NOT NULL."""
    sql = "select coalesce(name, 'anon') as name? from users"
    fields = await _annotate_with_resolver(schema_conn, sql)
    assert fields == {"name": "str | None"}


@skip_no_db
async def test_override_suffix_stripped_from_field_name(
    schema_conn: asyncpg.Connection,
) -> None:
    """The ``!`` / ``?`` is stripped — the generated model has ``created_at``, not ``created_at!``."""
    sql = "select u.created_at! from users u"
    fields = await _annotate_with_resolver(schema_conn, sql)
    assert "created_at" in fields
    assert "created_at!" not in fields


@skip_no_db
async def test_cte_left_join_nullable(
    schema_conn: asyncpg.Connection,
) -> None:
    """CTE wrapping a left join — nullability propagates through the flattened plan."""
    sql = (
        "with x as ("
        "  select u.id, o.name as org_name "
        "  from users u left join orgs o on o.id = u.org_id"
        ") "
        "select id, org_name from x"
    )
    fields = await _annotate(schema_conn, sql)
    assert fields["id"] == "int"
    assert fields["org_name"] == "str | None"


@skip_no_db
async def test_union_all_mixed_nullability(
    schema_conn: asyncpg.Connection,
) -> None:
    """UNION ALL of two selects with mixed nullability → nullable.

    Per the §14 note in ``project-plan.md``, a UNION ALL where one branch
    has a nullable column and the other doesn't should produce nullable.
    The Append node has no root ``Output`` list, so ``column_origins``
    returns ``(0, 0)`` for all columns and the catalog fallback correctly
    defaults to nullable. This is correct-by-accident: the v1.1 ``Append``
    work should handle this explicitly via the plan walker.
    """
    sql = "select id, email as name from users union all select id, name from users"
    fields = await _annotate(schema_conn, sql)
    # email (NOT NULL) in branch 1, name (nullable) in branch 2.
    # Conservative: nullable wins because Append has no root Output.
    assert fields["id"] == "int | None"
    assert fields["name"] == "str | None"


@skip_no_db
async def test_computed_expression_with_bang_override(
    schema_conn: asyncpg.Connection,
) -> None:
    """Computed expression with ``!`` override → forced non-null."""
    sql = "select count(*) as total! from users"
    fields = await _annotate(schema_conn, sql)
    assert fields["total"] == "int"  # forced non-null by !


# ---------------------------------------------------------------------------
# Fixture-file driven tests (each loads a .sql from nullability/)
# ---------------------------------------------------------------------------


@skip_no_db
async def test_fixture_left_join(
    schema_conn: asyncpg.Connection,
) -> None:
    """Load left_join.sql and verify via the full pipeline."""
    parsed = parse_sql_file(_FIXTURES / "left_join.sql")
    catalog = CatalogCache(schema_conn)
    resolver = TypeResolver(catalog)
    ir = await build_query_ir(schema_conn, parsed, resolver)

    field_map = {
        f.name: (
            f.py_type.annotation if not f.nullable else f"{f.py_type.annotation} | None"
        )
        for f in ir.fields
    }
    assert field_map == {"id": "int", "org_name": "str | None"}


@skip_no_db
async def test_fixture_inner_join(
    schema_conn: asyncpg.Connection,
) -> None:
    """Load inner_join.sql and verify via the full pipeline."""
    parsed = parse_sql_file(_FIXTURES / "inner_join.sql")
    catalog = CatalogCache(schema_conn)
    resolver = TypeResolver(catalog)
    ir = await build_query_ir(schema_conn, parsed, resolver)

    field_map = {
        f.name: (
            f.py_type.annotation if not f.nullable else f"{f.py_type.annotation} | None"
        )
        for f in ir.fields
    }
    assert field_map["id"] == "int"
    assert field_map["org_name"] == "str"


@skip_no_db
async def test_fixture_no_join(
    schema_conn: asyncpg.Connection,
) -> None:
    """Load no_join.sql and verify catalog-fallback nullability."""
    parsed = parse_sql_file(_FIXTURES / "no_join.sql")
    catalog = CatalogCache(schema_conn)
    resolver = TypeResolver(catalog)
    ir = await build_query_ir(schema_conn, parsed, resolver)

    field_map = {
        f.name: (
            f.py_type.annotation if not f.nullable else f"{f.py_type.annotation} | None"
        )
        for f in ir.fields
    }
    assert field_map["id"] == "int"
    assert field_map["email"] == "str"
    assert field_map["name"] == "str | None"


@skip_no_db
async def test_fixture_override_bang(
    schema_conn: asyncpg.Connection,
) -> None:
    """Load override_bang.sql and verify the ``!`` override is applied."""
    parsed = parse_sql_file(_FIXTURES / "override_bang.sql")
    catalog = CatalogCache(schema_conn)
    resolver = TypeResolver(catalog)
    ir = await build_query_ir(schema_conn, parsed, resolver)

    field_map = {
        f.name: (
            f.py_type.annotation if not f.nullable else f"{f.py_type.annotation} | None"
        )
        for f in ir.fields
    }
    # org_id! is forced non-null; the `!` is stripped from the field name.
    assert "org_id" in field_map
    assert field_map["org_id"] == "int"


@skip_no_db
async def test_fixture_computed(
    schema_conn: asyncpg.Connection,
) -> None:
    """Load computed.sql and verify no-origin column defaults to nullable."""
    parsed = parse_sql_file(_FIXTURES / "computed.sql")
    catalog = CatalogCache(schema_conn)
    resolver = TypeResolver(catalog)
    ir = await build_query_ir(schema_conn, parsed, resolver)

    field_map = {
        f.name: (
            f.py_type.annotation if not f.nullable else f"{f.py_type.annotation} | None"
        )
        for f in ir.fields
    }
    assert field_map["total"] == "int | None"


# ---------------------------------------------------------------------------
# Day 4 — fixture-file driven tests for overrides + edge cases
# ---------------------------------------------------------------------------


@skip_no_db
async def test_fixture_override_bang_left_join(
    schema_conn: asyncpg.Connection,
) -> None:
    """Override ``!`` + left join: ``created_at!`` non-null, ``org_name`` nullable."""
    parsed = parse_sql_file(_FIXTURES / "override_bang_left_join.sql")
    catalog = CatalogCache(schema_conn)
    resolver = TypeResolver(catalog)
    ir = await build_query_ir(schema_conn, parsed, resolver)

    field_map = {
        f.name: (
            f.py_type.annotation if not f.nullable else f"{f.py_type.annotation} | None"
        )
        for f in ir.fields
    }
    assert field_map == {"created_at": "datetime", "org_name": "str | None"}
    # Verify the `!` is stripped from the field name.
    assert "created_at!" not in field_map


@skip_no_db
async def test_fixture_override_qmark_coalesce(
    schema_conn: asyncpg.Connection,
) -> None:
    """Override ``?`` on coalesce: coalesce is NOT NULL, but ``?`` forces nullable."""
    parsed = parse_sql_file(_FIXTURES / "override_qmark_coalesce.sql")
    catalog = CatalogCache(schema_conn)
    resolver = TypeResolver(catalog)
    ir = await build_query_ir(schema_conn, parsed, resolver)

    field_map = {
        f.name: (
            f.py_type.annotation if not f.nullable else f"{f.py_type.annotation} | None"
        )
        for f in ir.fields
    }
    assert field_map == {"name": "str | None"}


@skip_no_db
async def test_fixture_cte_left_join(
    schema_conn: asyncpg.Connection,
) -> None:
    """CTE with left join — nullability propagates through the flattened plan."""
    parsed = parse_sql_file(_FIXTURES / "cte_left_join.sql")
    catalog = CatalogCache(schema_conn)
    resolver = TypeResolver(catalog)
    ir = await build_query_ir(schema_conn, parsed, resolver)

    field_map = {
        f.name: (
            f.py_type.annotation if not f.nullable else f"{f.py_type.annotation} | None"
        )
        for f in ir.fields
    }
    assert field_map["id"] == "int"
    assert field_map["org_name"] == "str | None"


@skip_no_db
async def test_fixture_union_all_mixed(
    schema_conn: asyncpg.Connection,
) -> None:
    """UNION ALL mixed nullability — falls back to nullable (correct-by-accident)."""
    parsed = parse_sql_file(_FIXTURES / "union_all_mixed.sql")
    catalog = CatalogCache(schema_conn)
    resolver = TypeResolver(catalog)
    ir = await build_query_ir(schema_conn, parsed, resolver)

    field_map = {
        f.name: (
            f.py_type.annotation if not f.nullable else f"{f.py_type.annotation} | None"
        )
        for f in ir.fields
    }
    # Both columns default to nullable because Append has no root Output.
    assert field_map["id"] == "int | None"
    assert field_map["name"] == "str | None"


@skip_no_db
async def test_fixture_computed_with_override(
    schema_conn: asyncpg.Connection,
) -> None:
    """Computed expression with ``!`` override → forced non-null."""
    parsed = parse_sql_file(_FIXTURES / "computed_with_override.sql")
    catalog = CatalogCache(schema_conn)
    resolver = TypeResolver(catalog)
    ir = await build_query_ir(schema_conn, parsed, resolver)

    field_map = {
        f.name: (
            f.py_type.annotation if not f.nullable else f"{f.py_type.annotation} | None"
        )
        for f in ir.fields
    }
    assert field_map["total"] == "int"
