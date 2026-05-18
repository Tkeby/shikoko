"""Postgres EXPLAIN plan parsing.

We run `EXPLAIN (FORMAT JSON, VERBOSE, GENERIC_PLAN) <query>` and parse the
resulting JSON into a `Plan` tree. The tree is then walked by
`nullability.py` to detect columns made nullable by outer joins.

Note on the JSON shape: Postgres returns a list with a single object whose
top-level key is "Plan", e.g.

    [
      {
        "Plan": {
          "Node Type": "Hash Join",
          "Join Type": "Left",
          "Output": ["u.id", "u.email", "o.name"],
          "Plans": [ ... ]
        }
      }
    ]

We don't care about most fields. Only "Join Type", "Output", and "Plans"
matter for nullability inference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

import asyncpg

JoinType = Literal["Inner", "Left", "Right", "Full", "Semi", "Anti"]
_KNOWN_JOIN_TYPES: frozenset[str] = frozenset(
    {"Inner", "Left", "Right", "Full", "Semi", "Anti"}
)

_UNEXPLAINABLE_SQLSTATES: frozenset[str] = frozenset(
    {
        "0A000",  # feature_not_supported (DO blocks)
        "42601",  # syntax_error from EXPLAIN wrapping
    }
)


@dataclass(frozen=True)
class Plan:
    """A single node in a Postgres query plan tree.

    Attributes:
        join_type: One of the Postgres join types if this node is a join,
            otherwise None. We deliberately keep only join types we know
            how to reason about; unrecognized strings become None.
        output: The list of column expressions this node emits, as
            reported by EXPLAIN VERBOSE. May be empty for nodes that
            don't surface in VERBOSE output (rare).
        plans: Child plan nodes. Joins always have two; Append/Union nodes
            can have many; leaf nodes have zero.
        relation_name: The table/view name for scan nodes (``Relation Name``
            in EXPLAIN output), or None for non-scan nodes.
        schema: The schema containing the relation (``Schema`` in EXPLAIN
            output), or None for non-scan nodes.
        alias: The table alias (``Alias`` in EXPLAIN output). Falls back
            to ``relation_name`` when no explicit alias was given.
    """

    join_type: JoinType | None
    output: tuple[str, ...]
    plans: tuple[Plan, ...]
    relation_name: str | None = None
    schema: str | None = None
    alias: str | None = None


def parse_plan_json(payload: Any) -> Plan:
    """Parse the JSON payload returned by EXPLAIN (FORMAT JSON) into a Plan.

    `payload` is whatever `json.loads()` produced from the EXPLAIN result.
    Accepts either the full top-level list form or an already-unwrapped
    inner dict, since callers may have already peeled one layer.

    Raises:
        ValueError: if the payload doesn't have the expected shape.
    """
    node = _unwrap_root(payload)
    return _parse_node(node)


def _unwrap_root(payload: Any) -> dict[str, Any]:
    # asyncpg returns the EXPLAIN result as a JSON string in row[0][0];
    # the caller is expected to json.loads() it before handing it here.
    # That gives us a list with one element: {"Plan": {...}}.
    if isinstance(payload, list):
        if not payload:
            raise ValueError("EXPLAIN returned an empty list")
        payload = payload[0]
    if not isinstance(payload, dict):
        raise ValueError(
            f"expected EXPLAIN root to be a dict, got {type(payload).__name__}"
        )
    if "Plan" in payload:
        inner = payload["Plan"]
        if not isinstance(inner, dict):
            raise ValueError("EXPLAIN root has 'Plan' key but it isn't a dict")
        return inner
    # Already unwrapped — caller handed us the inner dict directly.
    return payload


def _parse_node(node: dict[str, Any]) -> Plan:
    raw_join = node.get("Join Type")
    join_type: JoinType | None
    if isinstance(raw_join, str) and raw_join in _KNOWN_JOIN_TYPES:
        # mypy can't narrow a str membership check to a Literal, but the
        # check above is exhaustive against _KNOWN_JOIN_TYPES.
        join_type = raw_join  # type: ignore[assignment]
    else:
        join_type = None

    raw_output = node.get("Output") or []
    if not isinstance(raw_output, list):
        raise ValueError(
            f"plan node 'Output' must be a list, got {type(raw_output).__name__}"
        )
    output = tuple(str(item) for item in raw_output)

    raw_plans = node.get("Plans") or []
    if not isinstance(raw_plans, list):
        raise ValueError(
            f"plan node 'Plans' must be a list, got {type(raw_plans).__name__}"
        )
    plans = tuple(_parse_node(child) for child in raw_plans)

    relation_name = node.get("Relation Name")
    schema = node.get("Schema")
    alias = node.get("Alias") or relation_name

    return Plan(
        join_type=join_type,
        output=output,
        plans=plans,
        relation_name=relation_name,
        schema=schema,
        alias=alias,
    )


# ---------------------------------------------------------------------------
# EXPLAIN runner (I/O)
# ---------------------------------------------------------------------------


# Dummy values for each common Postgres type OID, used when binding
# EXPLAIN GENERIC_PLAN statements that contain $N placeholders.
# GENERIC_PLAN never evaluates the parameters, so the actual values
# don't matter — asyncpg just needs something it can encode.
_DUMMY_PARAM: dict[int, object] = {
    16: False,  # bool
    17: b"",  # bytea
    20: 0,  # int8
    21: 0,  # int2
    23: 0,  # int4
    26: 0,  # oid
    700: 0.0,  # float4
    701: 0.0,  # float8
    1700: 0,  # numeric
    25: "",  # text
    18: "",  # char
    19: "",  # name
    1042: "",  # bpchar
    1043: "",  # varchar
    1082: "2000-01-01",  # date
    1083: "00:00:00",  # time
    1114: "2000-01-01",  # timestamp
    1184: "2000-01-01",  # timestamptz
    1186: "00:00:00",  # interval
    1266: "00:00:00",  # timetz
    2950: "00000000-0000-0000-0000-000000000000",  # uuid
}


def _dummy_for_type(oid: int) -> object:
    """Return a dummy value that asyncpg can encode for *oid*.

    Falls back to the empty string for unknown types — this is safe
    because GENERIC_PLAN never evaluates the parameter.
    """
    return _DUMMY_PARAM.get(oid, "")


async def run_explain(conn: asyncpg.Connection, body: str) -> Plan | None:
    """Run EXPLAIN (FORMAT JSON, VERBOSE, GENERIC_PLAN) on *body*.

    Returns the parsed plan, or None if Postgres refuses to plan the
    statement (DO blocks, utility statements, multi-statement bodies).
    Any *other* asyncpg.PostgresError propagates — those are bugs we
    want to see, not silently swallow.
    """
    explain_sql = f"EXPLAIN (FORMAT JSON, VERBOSE, GENERIC_PLAN) {body}"

    try:
        # We need to discover the parameter types so asyncpg can bind
        # dummy values.  GENERIC_PLAN never evaluates parameters, but
        # asyncpg's extended-query protocol still requires the correct
        # number of encoded arguments at the Bind stage.
        stmt = await conn._get_statement(explain_sql, None)
        pg_params = stmt._get_parameters()
        dummy_args = [_dummy_for_type(p.oid) for p in pg_params]
        rows = await conn.fetch(explain_sql, *dummy_args)
    except asyncpg.PostgresError as exc:
        if _is_unexplainable(exc):
            return None
        raise

    if not rows:
        return None
    payload = rows[0][0]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return parse_plan_json(payload)


def _is_unexplainable(exc: asyncpg.PostgresError) -> bool:
    """Return True if *exc* is one of the "cannot explain" family."""
    return getattr(exc, "sqlstate", None) in _UNEXPLAINABLE_SQLSTATES


# ---------------------------------------------------------------------------
# Column origins from the plan (Plan B — §4.2 / §7.1)
# ---------------------------------------------------------------------------


def _collect_scan_aliases(plan: Plan) -> dict[str, tuple[str, str]]:
    """Walk the plan tree and return ``{alias: (schema, relation_name)}``.

    Only leaf scan nodes (nodes with ``relation_name is not None``) contribute.
    If two scans share the same alias the last one wins — that shouldn't
    happen in a valid plan.
    """
    result: dict[str, tuple[str, str]] = {}
    if (
        plan.relation_name is not None
        and plan.alias is not None
        and plan.schema is not None
    ):
        result[plan.alias] = (plan.schema, plan.relation_name)
    for child in plan.plans:
        result.update(_collect_scan_aliases(child))
    return result


async def column_origins(
    conn: asyncpg.Connection, plan: Plan, ncols: int
) -> list[tuple[int, int]]:
    """Map each output column to ``(table_oid, attnum)`` via the plan.

    Walks scan nodes for ``(schema, relation, alias)`` and the root
    ``Output`` list for per-column origins. Resolves ``schema.relation``
    to an oid via ``regclass`` and the column name to ``attnum``.
    Columns with no base-relation origin return ``(0, 0)`` so the
    catalog path leaves them nullable. Length is always ``ncols``.
    """
    alias_map = _collect_scan_aliases(plan)
    has_multiple_scans = len(alias_map) > 1

    origins: list[tuple[int, int]] = []
    for expr in plan.output:
        origin = _resolve_origin(expr, alias_map, has_multiple_scans)
        if origin is None:
            origins.append((0, 0))
            continue

        schema, relation, col_name = origin
        pair = await _lookup_table_attr(conn, schema, relation, col_name)
        origins.append(pair)

    # Pad if plan has fewer outputs than expected (shouldn't happen normally).
    while len(origins) < ncols:
        origins.append((0, 0))

    return origins


def _resolve_origin(
    expr: str,
    alias_map: dict[str, tuple[str, str]],
    has_multiple_scans: bool,
) -> tuple[str, str, str] | None:
    """Try to extract ``(schema, relation, col_name)`` from an output expression.

    Returns None for computed expressions that can't be traced to a
    single base-relation column.
    """
    # Qualified: "u.id" → alias "u", column "id"
    if "." in expr:
        parts = expr.split(".", 1)
        if len(parts) != 2:
            return None
        alias, col_name = parts
        # Parenthesized expressions like "u.(id + 1)" are computed.
        if col_name.startswith("("):
            return None
        entry = alias_map.get(alias)
        if entry is None:
            return None
        schema, relation = entry
        return (schema, relation, col_name)

    # Unqualified: only safe when there's a single scan.
    if has_multiple_scans:
        return None

    # Parenthesized or function calls are computed.
    if expr.startswith("(") or "(" in expr:
        return None

    # Single scan: the column belongs to it.
    if len(alias_map) == 1:
        schema, relation = next(iter(alias_map.values()))
        return (schema, relation, expr)

    return None


async def _lookup_table_attr(
    conn: asyncpg.Connection,
    schema: str,
    relation: str,
    col_name: str,
) -> tuple[int, int]:
    """Look up ``(table_oid, attnum)`` from ``pg_class`` + ``pg_attribute``."""
    row = await conn.fetchrow(
        """
        select c.oid as table_oid, a.attnum
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        join pg_attribute a on a.attrelid = c.oid
        where n.nspname = $1
          and c.relname = $2
          and a.attname = $3
          and a.attnum > 0
          and not a.attisdropped
        """,
        schema,
        relation,
        col_name,
    )
    if row is None:
        return (0, 0)
    return (row["table_oid"], row["attnum"])
