"""M3 acceptance: type mapping + enums across the full Postgres type matrix.

Each parametrized case asks the introspection layer to resolve a single
expression's type and asserts the resulting :class:`PyType` annotation
and required imports. The end-to-end test then exercises a real table
covering every supported type, generates code, runs the generated
function, and verifies the values round-trip.

Requires the test Postgres running on localhost:54323.
"""

from __future__ import annotations

import importlib.util
import socket
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from shikoko.codegen.ir import EnumIR, Field
from shikoko.codegen.render import render_module
from shikoko.introspect.catalog import CatalogCache
from shikoko.introspect.prepare import TypeResolver, build_query_ir
from shikoko.parser import ParsedQuery
from shikoko.types.enums import build_enum_ir, enum_member_name, enum_py_name


def _pg_reachable() -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        return sock.connect_ex(("localhost", 54323)) == 0
    finally:
        sock.close()


skip_no_db = pytest.mark.skipif(
    not _pg_reachable(),
    reason="Test Postgres not reachable on localhost:54323",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parsed(name: str, body: str, ret: str = "one") -> ParsedQuery:
    return ParsedQuery(
        name=name,
        doc="",
        body=body,
        annotations={"return_kind": ret},
        source_file=Path("inline.sql"),
        source_line=1,
    )


async def _resolve_single_field(
    conn: asyncpg.Connection, body: str
) -> tuple[Field, tuple[EnumIR, ...]]:
    catalog = CatalogCache(conn)
    resolver = TypeResolver(catalog)
    parsed = _parsed("expr_test", body)
    ir = await build_query_ir(conn, parsed, resolver)
    assert len(ir.fields) == 1, f"expected 1 field, got {ir.fields!r}"
    return ir.fields[0], ir.enums_used


# ---------------------------------------------------------------------------
# Unit-ish tests for the enum naming helpers (no DB required, but cheap so
# they ride along here).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,expected",
    [
        ("happy", "HAPPY"),
        ("in-progress", "IN_PROGRESS"),
        ("pending review", "PENDING_REVIEW"),
        ("snake_case", "SNAKE_CASE"),
        ("404", "_404"),
        ("CamelCase", "CAMELCASE"),
        ("---", "MEMBER"),
    ],
)
def test_enum_member_name(label: str, expected: str) -> None:
    assert enum_member_name(label) == expected


@pytest.mark.parametrize(
    "pg_name,expected",
    [
        ("mood", "Mood"),
        ("user_status", "UserStatus"),
        ("ORDER_STATUS", "OrderStatus"),
    ],
)
def test_enum_py_name(pg_name: str, expected: str) -> None:
    assert enum_py_name(pg_name) == expected


def test_build_enum_ir_resolves_collisions() -> None:
    # Two labels that normalise to the same member name should be
    # suffixed in label order.
    ir = build_enum_ir("priority", ("low", "low!"))
    assert ir.variants == (("LOW", "low"), ("LOW_2", "low!"))


# ---------------------------------------------------------------------------
# Scalar built-ins
# ---------------------------------------------------------------------------


@skip_no_db
@pytest.mark.parametrize(
    "sql_expr,expected_annotation,expected_imports",
    [
        ("true", "bool", frozenset()),
        ("1::int2", "int", frozenset()),
        ("1::int4", "int", frozenset()),
        ("1::int8", "int", frozenset()),
        ("1::float4", "float", frozenset()),
        ("1::float8", "float", frozenset()),
        ("1.5::numeric", "Decimal", frozenset({"from decimal import Decimal"})),
        ("'hello'::text", "str", frozenset()),
        ("'hello'::varchar(50)", "str", frozenset()),
        ("'h'::char(1)", "str", frozenset()),
        ("E'\\\\xDEAD'::bytea", "bytes", frozenset()),
        ("'2024-01-01'::date", "date", frozenset({"from datetime import date"})),
        ("'10:00'::time", "time", frozenset({"from datetime import time"})),
        ("'10:00+00'::timetz", "time", frozenset({"from datetime import time"})),
        (
            "'2024-01-01 10:00'::timestamp",
            "datetime",
            frozenset({"from datetime import datetime"}),
        ),
        (
            "'2024-01-01 10:00+00'::timestamptz",
            "datetime",
            frozenset({"from datetime import datetime"}),
        ),
        (
            "'1 day'::interval",
            "timedelta",
            frozenset({"from datetime import timedelta"}),
        ),
        (
            "gen_random_uuid()",
            "UUID",
            frozenset({"from uuid import UUID"}),
        ),
        ("'{}'::json", "Any", frozenset({"from typing import Any"})),
        ("'{}'::jsonb", "Any", frozenset({"from typing import Any"})),
        ("'<x/>'::xml", "str", frozenset()),
    ],
)
async def test_scalar_type_mapping(
    conn: asyncpg.Connection,
    sql_expr: str,
    expected_annotation: str,
    expected_imports: frozenset[str],
) -> None:
    field, enums = await _resolve_single_field(conn, f"select {sql_expr} as v")
    assert field.py_type.annotation == expected_annotation
    assert field.py_type.imports == expected_imports
    assert enums == ()


# ---------------------------------------------------------------------------
# Array types — built-in element types
# ---------------------------------------------------------------------------


@skip_no_db
@pytest.mark.parametrize(
    "sql_expr,expected_annotation",
    [
        ("array[1,2]::int2[]", "list[int]"),
        ("array[1,2]::int4[]", "list[int]"),
        ("array[1,2]::int8[]", "list[int]"),
        ("array[1.0]::float4[]", "list[float]"),
        ("array[1.0]::float8[]", "list[float]"),
        ("array[1.5]::numeric[]", "list[Decimal]"),
        ("array['a','b']::text[]", "list[str]"),
        ("array['a']::varchar[]", "list[str]"),
        ("array[true,false]::bool[]", "list[bool]"),
        ("array['2024-01-01'::date]::date[]", "list[date]"),
        ("array['10:00'::time]::time[]", "list[time]"),
        ("array[gen_random_uuid()]::uuid[]", "list[UUID]"),
        ("array['{}'::jsonb]::jsonb[]", "list[Any]"),
        (
            "array['2024-01-01 10:00'::timestamp]::timestamp[]",
            "list[datetime]",
        ),
        (
            "array['1 day'::interval]::interval[]",
            "list[timedelta]",
        ),
    ],
)
async def test_array_type_mapping(
    conn: asyncpg.Connection,
    sql_expr: str,
    expected_annotation: str,
) -> None:
    field, _ = await _resolve_single_field(conn, f"select {sql_expr} as v")
    assert field.py_type.annotation == expected_annotation


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


@pytest.fixture
async def mood_enum(conn: asyncpg.Connection):
    """Provide a fresh ``mood`` enum and tear it down after the test."""
    await conn.execute("drop type if exists mood cascade")
    await conn.execute(
        "create type mood as enum ('happy', 'sad', 'meh', 'in-progress')"
    )
    yield "mood"
    await conn.execute("drop type if exists mood cascade")


@skip_no_db
async def test_enum_scalar_field(conn: asyncpg.Connection, mood_enum: str) -> None:
    field, enums = await _resolve_single_field(conn, "select 'happy'::mood as m")
    assert field.py_type.annotation == "Mood"
    assert field.py_type.imports == frozenset()
    assert len(enums) == 1
    enum_ir = enums[0]
    assert enum_ir.py_name == "Mood"
    assert enum_ir.pg_name == "mood"
    assert enum_ir.variants == (
        ("HAPPY", "happy"),
        ("SAD", "sad"),
        ("MEH", "meh"),
        ("IN_PROGRESS", "in-progress"),
    )


@skip_no_db
async def test_enum_array_field(conn: asyncpg.Connection, mood_enum: str) -> None:
    field, enums = await _resolve_single_field(
        conn, "select array['happy'::mood, 'sad'::mood] as ms"
    )
    assert field.py_type.annotation == "list[Mood]"
    assert len(enums) == 1


@skip_no_db
async def test_enum_dedupe_across_queries(
    conn: asyncpg.Connection, mood_enum: str
) -> None:
    """Two queries referencing the same enum should share one EnumIR."""
    catalog = CatalogCache(conn)
    resolver = TypeResolver(catalog)
    ir_a = await build_query_ir(
        conn, _parsed("q1", "select 'happy'::mood as m"), resolver
    )
    ir_b = await build_query_ir(
        conn, _parsed("q2", "select 'sad'::mood as m"), resolver
    )
    src = render_module([ir_a, ir_b], "test")
    # The Mood class should be defined exactly once.
    assert src.count("class Mood(StrEnum):") == 1
    assert "from enum import StrEnum" in src


@skip_no_db
async def test_enum_class_renders_correctly(
    conn: asyncpg.Connection, mood_enum: str
) -> None:
    catalog = CatalogCache(conn)
    resolver = TypeResolver(catalog)
    ir = await build_query_ir(
        conn, _parsed("get_mood", "select 'happy'::mood as m"), resolver
    )
    src = render_module([ir], "test")

    assert "from enum import StrEnum" in src
    assert "class Mood(StrEnum):" in src
    assert "HAPPY = 'happy'" in src
    assert "SAD = 'sad'" in src
    assert "MEH = 'meh'" in src
    assert "IN_PROGRESS = 'in-progress'" in src


# ---------------------------------------------------------------------------
# End-to-end: real table with every supported type
# ---------------------------------------------------------------------------


_MATRIX_SCHEMA = """
drop type if exists order_status cascade;
create type order_status as enum ('pending', 'shipped', 'delivered');

drop table if exists matrix cascade;
create table matrix (
    id          int primary key,
    small       int2 not null,
    big         int8 not null,
    real_v      float4 not null,
    dbl         float8 not null,
    num         numeric(10, 4) not null,
    txt         text not null,
    vc          varchar(50) not null,
    ch          char(5) not null,
    blob        bytea not null,
    flag        bool not null,
    ts          timestamp not null,
    tstz        timestamptz not null,
    dt          date not null,
    tm          time not null,
    ivl         interval not null,
    uu          uuid not null,
    jb          jsonb not null,
    tags        text[] not null,
    scores      int4[] not null,
    st          order_status not null,
    sts         order_status[] not null
);
"""


@skip_no_db
async def test_introspect_full_type_matrix(conn: asyncpg.Connection) -> None:
    """Introspecting a SELECT over every supported type produces the right IR."""
    await conn.execute(_MATRIX_SCHEMA)
    try:
        catalog = CatalogCache(conn)
        resolver = TypeResolver(catalog)
        parsed = _parsed(
            "get_matrix",
            "select * from matrix where id = $1",
        )
        ir = await build_query_ir(conn, parsed, resolver)

        annotations = {f.name: f.py_type.annotation for f in ir.fields}
        assert annotations == {
            "id": "int",
            "small": "int",
            "big": "int",
            "real_v": "float",
            "dbl": "float",
            "num": "Decimal",
            "txt": "str",
            "vc": "str",
            "ch": "str",
            "blob": "bytes",
            "flag": "bool",
            "ts": "datetime",
            "tstz": "datetime",
            "dt": "date",
            "tm": "time",
            "ivl": "timedelta",
            "uu": "UUID",
            "jb": "Any",
            "tags": "list[str]",
            "scores": "list[int]",
            "st": "OrderStatus",
            "sts": "list[OrderStatus]",
        }

        # Enum discovered exactly once.
        enum_names = [e.pg_name for e in ir.enums_used]
        assert enum_names == ["order_status"]
        assert ir.enums_used[0].variants == (
            ("PENDING", "pending"),
            ("SHIPPED", "shipped"),
            ("DELIVERED", "delivered"),
        )

        # Param OID for $1 came from the int4 column.
        assert len(ir.params) == 1
        assert ir.params[0].py_type.annotation == "int"
    finally:
        await conn.execute("drop table if exists matrix cascade")
        await conn.execute("drop type if exists order_status cascade")


def _import_generated(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("sql_generated_types", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@skip_no_db
async def test_render_and_execute_full_matrix(
    conn: asyncpg.Connection, tmp_path: Path
) -> None:
    """Render generated code for a multi-type table, import it, and execute."""
    await conn.execute(_MATRIX_SCHEMA)
    try:
        await conn.execute(
            """
            insert into matrix values (
                1,                                  -- id
                5,                                  -- small (int2)
                10000000000,                        -- big (int8)
                1.5,                                -- real_v (float4)
                2.5,                                -- dbl (float8)
                3.1415,                             -- num
                'hello',                            -- txt
                'world',                            -- vc
                'ch__1',                            -- ch (char(5))
                decode('DEADBEEF', 'hex'),          -- blob
                true,                               -- flag
                '2024-01-01 10:00:00'::timestamp,   -- ts
                '2024-01-01 10:00:00+00'::timestamptz, -- tstz
                '2024-01-01'::date,                 -- dt
                '10:00:00'::time,                   -- tm
                '1 day'::interval,                  -- ivl
                '00000000-0000-0000-0000-000000000001'::uuid,
                '{"a":1}'::jsonb,                   -- jb
                array['x','y']::text[],             -- tags
                array[1,2]::int4[],                 -- scores
                'shipped'::order_status,            -- st
                array['pending'::order_status, 'shipped'::order_status]::order_status[]
            )
            """
        )

        catalog = CatalogCache(conn)
        resolver = TypeResolver(catalog)
        parsed = _parsed(
            "get_matrix",
            "select * from matrix where id = $1",
        )
        ir = await build_query_ir(conn, parsed, resolver)

        source = render_module([ir], "test_types")

        # Sanity-check the generated source.
        assert "from enum import StrEnum" in source
        assert "class OrderStatus(StrEnum):" in source
        assert "class GetMatrixRow(BaseModel):" in source

        out = tmp_path / "sql_generated_types.py"
        out.write_text(source, encoding="utf-8")

        mod = _import_generated(out)
        result = await mod.get_matrix(conn, 1)
        assert result is not None
        assert result.id == 1
        assert result.small == 5
        assert result.big == 10_000_000_000
        assert abs(result.real_v - 1.5) < 1e-6
        assert abs(result.dbl - 2.5) < 1e-9
        from decimal import Decimal

        assert result.num == Decimal("3.1415")
        assert result.txt == "hello"
        assert result.vc == "world"
        assert result.ch == "ch__1"
        assert result.blob == b"\xde\xad\xbe\xef"
        assert result.flag is True
        assert result.dt.year == 2024
        assert result.tm.hour == 10
        from datetime import timedelta

        assert result.ivl == timedelta(days=1)
        from uuid import UUID

        assert result.uu == UUID("00000000-0000-0000-0000-000000000001")
        assert result.tags == ["x", "y"]
        assert result.scores == [1, 2]
        # Enum values come through as the enum class.
        assert result.st == mod.OrderStatus.SHIPPED
        assert result.sts == [mod.OrderStatus.PENDING, mod.OrderStatus.SHIPPED]
    finally:
        await conn.execute("drop table if exists matrix cascade")
        await conn.execute("drop type if exists order_status cascade")
