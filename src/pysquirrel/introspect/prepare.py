"""Prepare a SQL statement via asyncpg and extract column/parameter metadata.

Param nullability is deliberately left as ``True`` for M4 — Postgres
doesn't give us NOT NULL info on parameters, and Squirrel doesn't
infer it either.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path

import asyncpg

from pysquirrel.codegen.ir import EnumIR, Field, Param, PyType, QueryIR, ReturnKind
from pysquirrel.codegen.naming import row_model_name
from pysquirrel.errors import IntrospectionError, UnsupportedTypeError
from pysquirrel.introspect.catalog import CatalogCache, TypeInfo
from pysquirrel.introspect.nullability import infer_nullability
from pysquirrel.introspect.plan import column_origins, run_explain
from pysquirrel.parser import ParsedQuery
from pysquirrel.types.enums import build_enum_ir
from pysquirrel.types.oid_map import (
    is_array_oid,
    resolve_builtin,
    resolve_type,
    wrap_array,
)
from pysquirrel.types.types import ColumnInfo, ParamInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level prepare helpers
# ---------------------------------------------------------------------------


async def prepare_query(
    conn: asyncpg.Connection,
    parsed: ParsedQuery,
) -> tuple[list[ColumnInfo], list[ParamInfo]]:
    """Prepare *parsed.body* and extract result-column and parameter metadata.

    Returns:
        A tuple of (columns, params) where *columns* describes the result
        set and *params* describes the $1, $2, … placeholders.

    Raises:
        IntrospectionError: if asyncpg raises during prepare.
    """
    try:
        stmt = await conn.prepare(parsed.body)
    except Exception as exc:
        raise IntrospectionError(
            file=parsed.source_file,
            message=str(exc),
        ) from exc

    columns: list[ColumnInfo] = []
    for attr in stmt.get_attributes():
        columns.append(
            ColumnInfo(
                name=attr.name,
                type_oid=attr.type.oid,
                table_oid=0,
                attr_number=0,
            )
        )

    params: list[ParamInfo] = []
    try:
        pg_params = stmt._state._get_parameters()
    except Exception as exc:
        raise IntrospectionError(
            file=parsed.source_file,
            message=f"failed to introspect parameters: {exc}",
        ) from exc

    for i, p in enumerate(pg_params):
        params.append(
            ParamInfo(
                name=f"_{i + 1}",
                type_oid=p.oid,
            )
        )

    return columns, params


# Pattern 1: matches ``AS identifier!`` / ``AS identifier?``.
_OVERRIDE_ALIAS_RE = re.compile(
    r"\bas\s+"  # 'as ' keyword
    r'("[^"]+"|\w+)'  # identifier (possibly double-quoted)
    r"([!?])"  # the override suffix
    r"(?=[\s,;)]|$)",  # followed by whitespace, comma, sem, paren, or EOS
    re.IGNORECASE,
)

# Pattern 2: matches ``table.column!`` / ``table.column?`` — a qualified
# column reference ending in an override marker, with no AS alias.
# We require the column to be preceded by a dotted qualifier (``alias.col``)
# to avoid false positives on ``!= `` (not-equal) or other operators.
_OVERRIDE_QUALIFIED_RE = re.compile(
    r"(\w+\.(?:\"[^\"]+\"|\w+))"  # ``alias.column`` (qualified reference)
    r"([!?])"  # the override suffix
    r"(?=[\s,;)]|$)",  # followed by whitespace, comma, sem, paren, or EOS
)


def _extract_overrides(sql: str) -> list[str | None]:
    """Extract ``!``/``?`` override suffixes from column aliases.

    Returns a list (one per select-list item in positional order) where
    each element is the override marker (``'!'`` or ``'?'``) or ``None``.
    Items without an ``AS ...!``/``AS ...?`` alias yield ``None``.

    This is a best-effort parser — it handles the common patterns
    (simple select lists, aliased expressions). CTEs, subqueries, and
    parenthesised expressions may confuse it, but those rarely carry
    override markers.
    """
    # Find the select list: everything between the first SELECT and
    # the first FROM/WHERE/GROUP/HAVING/ORDER/LIMIT/UNION that is not
    # inside parentheses.
    select_end = _find_select_list_end(sql)
    select_clause = sql[6:select_end]  # skip 'SELECT'

    # Split on commas that are not inside parentheses.
    items = _split_select_items(select_clause)

    overrides: list[str | None] = []
    for item in items:
        m = _OVERRIDE_ALIAS_RE.search(item)
        if m:
            overrides.append(m.group(2))
        else:
            # Also check for qualified-column overrides: ``u.col!``
            m2 = _OVERRIDE_QUALIFIED_RE.search(item)
            if m2:
                overrides.append(m2.group(2))
            else:
                overrides.append(None)
    return overrides


def _find_select_list_end(sql: str) -> int:
    """Return the index just past the last select-list column.

    Scans for the first top-level keyword that terminates the select
    list (FROM, WHERE, GROUP BY, HAVING, ORDER BY, LIMIT, UNION,
    INTERSECT, EXCEPT, FOR) while respecting parenthesised expressions.
    """
    depth = 0
    upper = sql.upper()
    i = 6  # skip 'SELECT'
    while i < len(sql):
        ch = sql[i]
        if ch == "(":
            depth += 1
            i += 1
        elif ch == ")":
            depth -= 1
            i += 1
        elif depth == 0:
            # Check for terminating keywords at the top level.
            rest = upper[i:]
            for kw in (
                "FROM",
                "WHERE",
                "GROUP BY",
                "HAVING",
                "ORDER BY",
                "LIMIT",
                "UNION",
                "INTERSECT",
                "EXCEPT",
                "FOR",
            ):
                if rest.startswith(kw) and (
                    i + len(kw) >= len(sql) or not rest[len(kw)].isalnum()
                ):
                    return i
            i += 1
        else:
            i += 1
    return len(sql)


def _split_select_items(clause: str) -> list[str]:
    """Split a select clause on top-level commas."""
    items: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(clause):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            items.append(clause[start:i].strip())
            start = i + 1
    items.append(clause[start:].strip())
    return items


def _strip_override_suffixes(sql: str) -> str:
    """Remove pysquirrel ``!``/``?`` override suffixes from column aliases.

    Postgres doesn't understand ``!``/``?`` as part of an identifier.
    These are pysquirrel-specific annotations that must be stripped
    before sending the SQL to ``conn.prepare()``. The suffix is stripped
    from two positions:

    1. After ``AS`` in a select-list alias: ``as name!`` → ``as name``
    2. On qualified column references: ``u.col!`` → ``u.col``
    """
    sql = _OVERRIDE_ALIAS_RE.sub(r"as \1", sql)
    sql = _OVERRIDE_QUALIFIED_RE.sub(r"\1", sql)
    return sql


async def _prepare_raw(
    conn: asyncpg.Connection,
    parsed: ParsedQuery,
) -> tuple[list[tuple[str, int, str]], list[tuple[int, str]]]:
    """Low-level prepare returning raw asyncpg type metadata.

    Returns:
        columns: list of (name, oid, kind) for each result column.
        params: list of (oid, kind) for each parameter.
    """
    # Strip pysquirrel-specific ``!``/``?`` override suffixes from
    # column aliases before preparing — Postgres doesn't understand them.
    # Capture the suffixes first so we can re-apply them to the column
    # names returned by asyncpg (which sees the stripped aliases).
    overrides = _extract_overrides(parsed.body)
    body = _strip_override_suffixes(parsed.body)
    try:
        stmt = await conn.prepare(body)
    except Exception as exc:
        raise IntrospectionError(
            file=parsed.source_file,
            message=str(exc),
        ) from exc

    columns: list[tuple[str, int, str]] = []
    for i, attr in enumerate(stmt.get_attributes()):
        name = attr.name
        # Re-apply the override suffix so the nullability module can
        # see and process it.
        if i < len(overrides) and overrides[i] is not None:
            name = name + overrides[i]
        columns.append((name, attr.type.oid, attr.type.kind))

    params: list[tuple[int, str]] = []
    try:
        pg_params = stmt._state._get_parameters()
    except Exception as exc:
        raise IntrospectionError(
            file=parsed.source_file,
            message=f"failed to introspect parameters: {exc}",
        ) from exc

    for p in pg_params:
        params.append((p.oid, p.kind))

    return columns, params


# ---------------------------------------------------------------------------
# Type resolution with catalog support (enums, user-defined arrays)
# ---------------------------------------------------------------------------


class TypeResolver:
    """Resolve Postgres OIDs to :class:`PyType` with catalog fallback.

    Built-in OIDs (numeric, text, datetime, etc.) and built-in array
    OIDs are answered from the static table in
    :mod:`pysquirrel.types.oid_map`. Anything else — enums, arrays of
    user-defined types — is resolved by querying ``pg_type`` via the
    :class:`CatalogCache`.

    Enums encountered during resolution are accumulated on the resolver
    so the renderer can emit one ``StrEnum`` class per distinct enum
    type. Enums are deduplicated by their Postgres name: two queries
    that reference the same ``mood`` enum produce a single ``Mood``
    class in the generated module.
    """

    def __init__(self, catalog: CatalogCache) -> None:
        self._catalog = catalog
        # OID → EnumIR. Keyed by OID for fast hit detection; the
        # renderer deduplicates by pg_name when assembling the final
        # module (two enums with the same name in different schemas
        # would still collide there, but that is a v1 limitation).
        self._enums: dict[int, EnumIR] = {}

    async def resolve(self, oid: int, type_name: str, kind: str) -> PyType:
        """Resolve a single OID. Side-effect: records enum metadata."""
        # Arrays: dispatch on the array OID itself.
        if kind == "array":
            return await self._resolve_array(oid, type_name)

        # Built-in scalar fast path.
        builtin = resolve_builtin(oid)
        if builtin is not None:
            return builtin

        # Non-builtin scalar: ask the catalog.
        info = await self._catalog.type_info(oid)
        if info is None:
            raise UnsupportedTypeError(
                file=_introspection_path(),
                oid=oid,
                pg_type_name=type_name,
            )

        if info.typtype == "e":
            return await self._resolve_enum(info)

        # Domains, composites, ranges, pseudo, multirange: not in v1.
        raise UnsupportedTypeError(
            file=_introspection_path(),
            oid=oid,
            pg_type_name=info.typname,
        )

    async def _resolve_array(self, array_oid: int, type_name: str) -> PyType:
        elem_oid = is_array_oid(array_oid)
        if elem_oid is None:
            # User-defined array (e.g. enum[]). Look up the element OID.
            info = await self._catalog.type_info(array_oid)
            if info is None or info.typelem == 0:
                raise UnsupportedTypeError(
                    file=_introspection_path(),
                    oid=array_oid,
                    pg_type_name=type_name,
                )
            elem_oid = info.typelem

        # Recurse on the element type as a scalar — element OIDs are
        # never themselves array OIDs.
        elem_type = await self.resolve(elem_oid, type_name, "scalar")
        return wrap_array(elem_type)

    async def _resolve_enum(self, info: TypeInfo) -> PyType:
        cached = self._enums.get(info.oid)
        if cached is None:
            labels = await self._catalog.enum_labels(info.oid)
            cached = build_enum_ir(info.typname, labels)
            self._enums[info.oid] = cached
        return PyType(annotation=cached.py_name, imports=frozenset())

    def enums_used(self) -> tuple[EnumIR, ...]:
        """Return all enums discovered so far, in OID order.

        OID order is stable for a given Postgres instance and gives the
        renderer a deterministic baseline; the renderer applies its own
        alphabetical sort before emitting, so order here is just an
        accumulator detail.
        """
        return tuple(self._enums[oid] for oid in sorted(self._enums))


def _introspection_path() -> Path:
    """Module-level constant Path used in UnsupportedTypeError without I/O."""
    return Path("<introspection>")


# ---------------------------------------------------------------------------
# IR construction
# ---------------------------------------------------------------------------


async def build_query_ir(
    conn: asyncpg.Connection,
    parsed: ParsedQuery,
    resolver: TypeResolver | Callable[[int, str, str], PyType],
) -> QueryIR:
    """Build a fully-populated :class:`QueryIR` for a single parsed query.

    Two resolver shapes are accepted for ergonomics:

    * A :class:`TypeResolver` instance — recommended; supports enums and
      user-defined arrays.
    * A plain sync callable ``(oid, name, kind) -> PyType`` — kept for
      backwards compatibility with M2 tests that pass ``resolve_type``
      directly. Plain callables cannot discover enums, so any non-builtin
      OID will surface as :class:`UnsupportedTypeError`.
    """
    raw_columns, raw_params = await _prepare_raw(conn, parsed)

    is_resolver_obj = isinstance(resolver, TypeResolver)

    async def _resolve(oid: int, name: str, kind: str) -> PyType:
        if is_resolver_obj:
            return await resolver.resolve(oid, name, kind)  # type: ignore[union-attr]
        return resolver(oid, name, kind)  # type: ignore[operator]

    # Determine return kind from annotations.
    return_kind_str = parsed.annotations.get("return_kind", "many")
    return_kind = ReturnKind(return_kind_str)

    # Resolve parameter types.
    ir_params: list[Param] = []
    for i, (oid, kind) in enumerate(raw_params):
        py_type = await _resolve(oid, f"param _{i + 1}", kind)
        ir_params.append(Param(name=f"_{i + 1}", py_type=py_type, nullable=True))

    # --- Nullability inference (M4) ---
    #
    # Run EXPLAIN to get the plan tree, then extract column origins
    # from the plan's scan nodes. Origins feed both the join-nullability
    # walker and the catalog NOT NULL fallback.
    plan = await run_explain(conn, _strip_override_suffixes(parsed.body))
    if plan is not None:
        origins = await column_origins(conn, plan, len(raw_columns))
    else:
        origins = [(0, 0)] * len(raw_columns)

    col_infos = [
        ColumnInfo(
            name=name,
            type_oid=oid,
            table_oid=tbl_oid,
            attr_number=attnum,
        )
        for (name, oid, _kind), (tbl_oid, attnum) in zip(
            raw_columns, origins, strict=True
        )
    ]

    # Build an attnotnull lookup from the resolver's catalog (or a
    # one-shot CatalogCache for the legacy plain-callable path).
    catalog = resolver._catalog if is_resolver_obj else CatalogCache(conn)  # type: ignore[union-attr]

    async def _attnotnull(table_oid: int, attr_number: int) -> bool:
        return await catalog.attnotnull(table_oid, attr_number)

    decisions = await infer_nullability(col_infos, plan, _attnotnull)

    # Resolve field types using the decided names and nullability.
    ir_fields: list[Field] = []
    for (col_name, oid, kind), decision in zip(raw_columns, decisions, strict=True):
        py_type = await _resolve(oid, col_name, kind)
        ir_fields.append(
            Field(name=decision.clean_name, py_type=py_type, nullable=decision.nullable)
        )

    # Determine row model name.
    model_name = row_model_name(parsed.name) if return_kind != ReturnKind.EXEC else ""

    # Enums used in this specific query. The resolver accumulates across
    # all queries it's used for; here we filter down to the ones that
    # actually appear in this query's params or fields by matching
    # against the rendered PyType.annotation. This is a small bit of
    # bookkeeping that keeps QueryIR self-contained for tests, but the
    # renderer ultimately unions all queries' enums anyway.
    enums_used: tuple[EnumIR, ...] = ()
    if is_resolver_obj:
        all_enums = resolver.enums_used()  # type: ignore[union-attr]
        used_names = {p.py_type.annotation for p in ir_params}
        for f in ir_fields:
            used_names.add(f.py_type.annotation)
            # Strip list[...] wrappers so enum-array fields count too.
            ann = f.py_type.annotation
            if ann.startswith("list[") and ann.endswith("]"):
                used_names.add(ann[5:-1])
        enums_used = tuple(e for e in all_enums if e.py_name in used_names)

    return QueryIR(
        name=parsed.name,
        doc=parsed.doc,
        sql=parsed.body,
        params=tuple(ir_params),
        row_model_name=model_name,
        fields=tuple(ir_fields),
        return_kind=return_kind,
        enums_used=enums_used,
        source_file=str(parsed.source_file),
        source_line=parsed.source_line,
    )


# Re-export ``resolve_type`` for callers that import from this module.
__all__ = [
    "TypeResolver",
    "build_query_ir",
    "prepare_query",
    "resolve_type",
]
