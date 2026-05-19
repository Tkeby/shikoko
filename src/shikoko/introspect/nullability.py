"""Nullability inference for query result columns.

This is a direct port of the algorithm in Squirrels's
`src/squirrel/internal/database/postgres.gleam`. Given the RowDescription
returned by Postgres after preparing a statement plus the EXPLAIN plan
for that statement, decide which output columns can be NULL.

The algorithm is four steps, in order:

    1. Honor explicit overrides on column aliases:
         - trailing `!` => force non-null
         - trailing `?` => force nullable

    2. Walk the EXPLAIN plan tree to find columns made nullable by outer
       joins. The rules are:
         - Full Join:   every output of this node is nullable.
         - Right Join:  every output of the LEFT child is nullable.
         - Left Join:   every output of the RIGHT child is nullable.
         - Semi Join:   treated like Left Join (squirrel does this; in
                        practice semi joins don't surface columns from
                        the inner side, but the rule is safe).
         - Anti Join:   treated like inner — no contribution. Anti joins
                        only emit left-side rows where no right-side
                        match exists, so right-side columns aren't in
                        the output at all.
         - Inner Join:  no contribution; recurse into children.
         - No join:     recurse into children.
       Plan outputs are matched back to final result columns by name.

    3. If EXPLAIN itself failed (DO blocks etc.), the plan-derived set is
       empty. This is handled by the caller; this module just consumes
       whatever Plan it's given.

    4. For any column not yet decided, fall back to `pg_attribute.attnotnull`
       for the column's (table_oid, attr_number). Columns with no
       originating table (computed expressions) default to nullable, which
       is the conservative choice: any null operand makes the whole
       expression null.

The module exposes one async entry point, `infer_nullability`, plus the
pure functions that drive it. The pure functions take no I/O and form
the bulk of the test surface.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from shikoko.introspect.plan import Plan
from shikoko.types.types import ColumnInfo

__all__ = [
    "AttnotnullLookup",
    "NullabilityDecision",
    "infer_nullability",
    "strip_override_suffix",
    "apply_overrides",
    "nullables_from_plan",
]


# A callback the caller supplies to look up pg_attribute.attnotnull.
# Returning True means "the column has a NOT NULL constraint".
# This indirection keeps the inference pure-ish and lets tests inject a
# dict-backed fake instead of standing up a real Postgres instance.
class AttnotnullLookup(Protocol):
    def __call__(self, table_oid: int, attr_number: int) -> Awaitable[bool]: ...


@dataclass(frozen=True)
class NullabilityDecision:
    """The result of inference for a single column.

    `clean_name` has any trailing `!`/`?` override marker stripped, so
    it's safe to use directly as a Python field name.
    """

    clean_name: str
    nullable: bool


# --- Step 1: override suffixes -----------------------------------------------


def strip_override_suffix(name: str) -> tuple[str, bool | None]:
    """Split a column name into (clean_name, override).

    The override is True for `?` (force nullable), False for `!` (force
    non-null), or None if there's no override marker. We strip exactly
    one trailing marker; `foo!!` keeps one `!` in the clean name, which
    will then fail Python identifier validation downstream — that's the
    right place to surface it.
    """
    if not name:
        return name, None
    last = name[-1]
    if last == "!":
        return name[:-1], False
    if last == "?":
        return name[:-1], True
    return name, None


def apply_overrides(
    columns: list[ColumnInfo],
) -> tuple[list[str], list[bool | None]]:
    """Return parallel lists of clean names and per-column override flags.

    The override flag is True (nullable) / False (non-null) / None (no
    override, decide later).
    """
    clean_names: list[str] = []
    overrides: list[bool | None] = []
    for col in columns:
        clean, override = strip_override_suffix(col.name)
        clean_names.append(clean)
        overrides.append(override)
    return clean_names, overrides


# --- Step 2: plan-tree walk --------------------------------------------------


def nullables_from_plan(plan: Plan) -> set[int]:
    """Return the set of result-column indices made nullable by outer joins.

    The returned indices are positions in the root plan node's `output`
    list, which Postgres guarantees is in the same order as the
    statement's RowDescription. So callers should consume the returned
    set positionally against their RowDescription / ColumnInfo list.

    Plan-node outputs are matched back to the root's output list by
    exact string equality, mirroring Squirrel's. Intermediate expressions
    that don't appear in the root output are silently ignored — they
    were projected away before reaching the user-visible result, so
    their nullability is irrelevant.
    """
    # Build expression -> root-output index. If two root outputs share
    # the same expression text (rare but possible in pathological
    # queries) the later one wins, matching Squirrel's `dict.insert`
    # fold-left behavior.
    output_to_idx: dict[str, int] = {expr: i for i, expr in enumerate(plan.output)}
    acc: set[int] = set()
    _walk(plan, output_to_idx, acc)
    return acc


def _plan_output_indices(plan: Plan, output_to_idx: dict[str, int]) -> set[int]:
    # Map a plan node's Output expressions to root-output indices by
    # exact match. No qualifier munging: Postgres emits the same
    # expression text for a given column at every level of the plan
    # where it's projected.
    out: set[int] = set()
    for expr in plan.output:
        idx = output_to_idx.get(expr)
        if idx is not None:
            out.add(idx)
    return out


def _walk(
    plan: Plan,
    name_to_idx: dict[str, int],
    acc: set[int],
) -> None:
    jt = plan.join_type
    children = plan.plans

    if jt == "Full":
        # Every output of a full join is nullable on both sides.
        acc.update(_plan_output_indices(plan, name_to_idx))
        for child in children:
            _walk(child, name_to_idx, acc)
        return

    if jt == "Right" and len(children) == 2:
        # Right join: rows from the LEFT side may be missing, so left
        # outputs are nullable.
        left, right = children
        acc.update(_plan_output_indices(left, name_to_idx))
        _walk(right, name_to_idx, acc)
        return

    if jt in ("Left", "Semi") and len(children) == 2:
        # Left/semi join: right-side outputs may be missing.
        left, right = children
        acc.update(_plan_output_indices(right, name_to_idx))
        _walk(left, name_to_idx, acc)
        return

    # Inner, Anti, None, or anomalous shape: just recurse.
    # - Inner: no rows are made null by the join itself.
    # - Anti: only left-side rows survive, so right-side cols aren't in
    #   the output anyway; safe to recurse without contributing.
    # - None: append/sort/scan/etc.
    for child in children:
        _walk(child, name_to_idx, acc)


# --- Step 4: catalog fallback + orchestration --------------------------------


async def infer_nullability(
    columns: list[ColumnInfo],
    plan: Plan | None,
    attnotnull: AttnotnullLookup,
) -> list[NullabilityDecision]:
    """Run the full pipeline and return one decision per input column.

    Args:
        columns: The result-column metadata from the prepared statement.
        plan: The parsed EXPLAIN plan tree, or None if EXPLAIN failed.
            None is treated as "no join nullability info available" —
            the algorithm proceeds with overrides + catalog only.
        attnotnull: Async callback to look up pg_attribute.attnotnull.
            Must return True iff the column has a NOT NULL constraint.

    Returns:
        A list of NullabilityDecision, one per input column, in the same
        order. Each decision carries the cleaned name (override marker
        stripped) and the final nullable bool.
    """
    clean_names, overrides = apply_overrides(columns)

    plan_nullable = nullables_from_plan(plan) if plan is not None else set()

    decisions: list[NullabilityDecision] = []
    for i, col in enumerate(columns):
        # Step 1: explicit overrides win unconditionally.
        if overrides[i] is not None:
            decisions.append(
                NullabilityDecision(
                    clean_name=clean_names[i],
                    nullable=overrides[i],  # type: ignore[arg-type]
                )
            )
            continue

        # Step 2: plan says nullable.
        if i in plan_nullable:
            decisions.append(
                NullabilityDecision(clean_name=clean_names[i], nullable=True)
            )
            continue

        # Step 4: catalog fallback. Computed expressions with no origin
        # table default to nullable.
        if col.table_oid == 0 or col.attr_number <= 0:
            decisions.append(
                NullabilityDecision(clean_name=clean_names[i], nullable=True)
            )
            continue

        has_not_null = await attnotnull(col.table_oid, col.attr_number)
        decisions.append(
            NullabilityDecision(clean_name=clean_names[i], nullable=not has_not_null)
        )

    return decisions


def make_dict_lookup(
    table: dict[tuple[int, int], bool],
) -> AttnotnullLookup:
    """Build an AttnotnullLookup backed by a plain dict. Useful in tests."""

    async def _lookup(table_oid: int, attr_number: int) -> bool:
        return table.get((table_oid, attr_number), False)

    return _lookup
