"""Unit tests for the full nullability inference pipeline.

Tests strip_override_suffix, apply_overrides, and infer_nullability
(the async orchestrator) using hand-rolled data and a dict-backed
attnotnull lookup. No Postgres needed.
"""

from __future__ import annotations

from shikoko.introspect.nullability import (
    NullabilityDecision,
    apply_overrides,
    infer_nullability,
    make_dict_lookup,
    strip_override_suffix,
)
from shikoko.introspect.plan import Plan
from shikoko.types.types import ColumnInfo

# ---------------------------------------------------------------------------
# strip_override_suffix
# ---------------------------------------------------------------------------


class TestStripOverrideSuffix:
    def test_bang_forces_non_null(self) -> None:
        assert strip_override_suffix("name!") == ("name", False)

    def test_qmark_forces_nullable(self) -> None:
        assert strip_override_suffix("name?") == ("name", True)

    def test_no_marker_no_override(self) -> None:
        assert strip_override_suffix("name") == ("name", None)

    def test_empty_string(self) -> None:
        assert strip_override_suffix("") == ("", None)

    def test_single_bang(self) -> None:
        assert strip_override_suffix("!") == ("", False)

    def test_single_qmark(self) -> None:
        assert strip_override_suffix("?") == ("", True)

    def test_double_bang_strips_one(self) -> None:
        assert strip_override_suffix("foo!!") == ("foo!", False)

    def test_double_qmark_strips_one(self) -> None:
        assert strip_override_suffix("foo??") == ("foo?", True)


# ---------------------------------------------------------------------------
# apply_overrides
# ---------------------------------------------------------------------------


class TestApplyOverrides:
    def test_mixed_columns(self) -> None:
        columns = [
            ColumnInfo(name="id", type_oid=23, table_oid=1234, attr_number=1),
            ColumnInfo(name="name!", type_oid=25, table_oid=1234, attr_number=2),
            ColumnInfo(name="bio?", type_oid=25, table_oid=1234, attr_number=3),
        ]
        clean_names, overrides = apply_overrides(columns)
        assert clean_names == ["id", "name", "bio"]
        assert overrides == [None, False, True]

    def test_empty_columns_list(self) -> None:
        clean_names, overrides = apply_overrides([])
        assert clean_names == []
        assert overrides == []


# ---------------------------------------------------------------------------
# infer_nullability — the full pipeline
# ---------------------------------------------------------------------------


def _col(
    name: str,
    table_oid: int = 0,
    attr_number: int = 0,
    type_oid: int = 25,
) -> ColumnInfo:
    """Shorthand for building a ColumnInfo."""
    return ColumnInfo(
        name=name,
        type_oid=type_oid,
        table_oid=table_oid,
        attr_number=attr_number,
    )


class TestInferNullability:
    """Integration-level tests for the pure inference pipeline.

    Each test builds ColumnInfo lists, optionally a Plan tree, and a
    dict-backed attnotnull lookup, then asserts the final decisions.
    """

    async def test_override_beats_catalog(self) -> None:
        """`name!` is non-null even if catalog says nullable."""
        columns = [_col("name!", table_oid=100, attr_number=2)]
        attnotnull = make_dict_lookup({})  # nothing is NOT NULL
        decisions = await infer_nullability(columns, plan=None, attnotnull=attnotnull)
        assert decisions == [NullabilityDecision(clean_name="name", nullable=False)]

    async def test_override_qmark_with_inner_join(self) -> None:
        """`name?` is nullable even when the plan would not mark it nullable.

        Inner-join columns don't enter the plan-derived nullable set, so
        without the override the column would be decided by the catalog
        (here: NOT NULL → non-null). The `?` override flips it to
        nullable.
        """
        inner_plan = Plan(
            join_type="Inner",
            output=("name",),
            plans=(
                Plan(join_type=None, output=("name",), plans=()),
                Plan(join_type=None, output=("name",), plans=()),
            ),
        )
        columns = [_col("name?", table_oid=100, attr_number=2)]
        attnotnull = make_dict_lookup({(100, 2): True})  # catalog: NOT NULL
        decisions = await infer_nullability(
            columns, plan=inner_plan, attnotnull=attnotnull
        )
        assert decisions == [NullabilityDecision(clean_name="name", nullable=True)]

    async def test_override_bang_beats_plan_says_nullable(self) -> None:
        """`name!` is non-null even when the plan marks it nullable.

        This is the strict override-vs-plan precedence case: the column
        is on the right side of a left join, so the plan walker would
        return it in the nullable set. The `!` override forces non-null
        anyway.
        """
        plan = Plan(
            join_type="Left",
            output=("u.id", "o.name"),
            plans=(
                Plan(join_type=None, output=("u.id",), plans=()),
                Plan(join_type=None, output=("o.name",), plans=()),
            ),
        )
        columns = [
            _col("u.id", table_oid=100, attr_number=1),
            _col("o.name!", table_oid=200, attr_number=2),
        ]
        attnotnull = make_dict_lookup({})
        decisions = await infer_nullability(columns, plan=plan, attnotnull=attnotnull)
        assert decisions[1] == NullabilityDecision(clean_name="o.name", nullable=False)

    async def test_plan_wins_over_catalog(self) -> None:
        """Left-join right-side column is nullable even if catalog says NOT NULL."""
        plan = Plan(
            join_type="Left",
            output=("u.id", "o.name"),
            plans=(
                Plan(join_type=None, output=("u.id",), plans=()),
                Plan(join_type=None, output=("o.name",), plans=()),
            ),
        )
        columns = [
            _col("u.id", table_oid=100, attr_number=1),
            _col("o.name", table_oid=200, attr_number=2),
        ]
        # Catalog says both columns have NOT NULL constraints.
        # The left join overrides that for o.name.
        attnotnull = make_dict_lookup({(100, 1): True, (200, 2): True})
        decisions = await infer_nullability(columns, plan=plan, attnotnull=attnotnull)
        assert decisions[0].nullable is False  # u.id: catalog says not null
        assert decisions[1].nullable is True  # o.name: plan says nullable

    async def test_catalog_wins_when_no_plan_info(self) -> None:
        """No plan info → fall back to catalog attnotnull."""
        columns = [
            _col("email", table_oid=100, attr_number=2),
            _col("bio", table_oid=100, attr_number=3),
        ]
        # email is NOT NULL in the catalog, bio is nullable.
        attnotnull = make_dict_lookup({(100, 2): True})
        decisions = await infer_nullability(columns, plan=None, attnotnull=attnotnull)
        assert decisions[0].nullable is False  # email: catalog says not null
        assert decisions[1].nullable is True  # bio: catalog says nullable

    async def test_table_oid_zero_implies_nullable(self) -> None:
        """Columns with table_oid == 0 (computed expressions) → nullable.

        The attnotnull lookup is seeded with a (0, 0) → True entry that
        would otherwise force non-null; the early-return must fire and
        skip the catalog call.
        """
        columns = [_col("total", table_oid=0, attr_number=0)]
        attnotnull = make_dict_lookup({(0, 0): True})
        decisions = await infer_nullability(columns, plan=None, attnotnull=attnotnull)
        assert decisions == [NullabilityDecision(clean_name="total", nullable=True)]

    async def test_attr_number_le_zero_implies_nullable(self) -> None:
        """Columns with attr_number <= 0 → nullable.

        Seed the catalog with a contradicting NOT NULL entry to prove
        the early-return fires before the lookup runs.
        """
        columns = [_col("total", table_oid=100, attr_number=-1)]
        attnotnull = make_dict_lookup({(100, -1): True})
        decisions = await infer_nullability(columns, plan=None, attnotnull=attnotnull)
        assert decisions == [NullabilityDecision(clean_name="total", nullable=True)]

    async def test_attr_number_zero_implies_nullable(self) -> None:
        """Columns with attr_number == 0 → nullable.

        Seed the catalog with a contradicting NOT NULL entry to prove
        the early-return fires before the lookup runs.
        """
        columns = [_col("total", table_oid=100, attr_number=0)]
        attnotnull = make_dict_lookup({(100, 0): True})
        decisions = await infer_nullability(columns, plan=None, attnotnull=attnotnull)
        assert decisions == [NullabilityDecision(clean_name="total", nullable=True)]

    async def test_empty_columns_empty_decisions(self) -> None:
        """Empty columns list → empty decisions list (no crash)."""
        attnotnull = make_dict_lookup({})
        decisions = await infer_nullability([], plan=None, attnotnull=attnotnull)
        assert decisions == []

    async def test_plan_none_uses_no_plan_info(self) -> None:
        """plan=None → no plan-derived nullability; catalog decides."""
        columns = [_col("id", table_oid=100, attr_number=1)]
        attnotnull = make_dict_lookup({(100, 1): True})
        decisions = await infer_nullability(columns, plan=None, attnotnull=attnotnull)
        assert decisions[0].nullable is False

    async def test_full_pipeline_mixed(self) -> None:
        """Full pipeline with overrides, plan, and catalog together."""
        plan = Plan(
            join_type="Left",
            output=("id", "name", "email"),
            plans=(
                Plan(join_type=None, output=("id", "name"), plans=()),
                Plan(join_type=None, output=("email",), plans=()),
            ),
        )
        columns = [
            _col("id", table_oid=100, attr_number=1),  # catalog: NOT NULL
            _col("name?", table_oid=100, attr_number=2),  # override: nullable
            _col(
                "email", table_oid=200, attr_number=1
            ),  # plan: nullable (right side of left join)
        ]
        attnotnull = make_dict_lookup({(100, 1): True, (100, 2): True, (200, 1): True})
        decisions = await infer_nullability(columns, plan=plan, attnotnull=attnotnull)
        assert (
            decisions[0].nullable is False
        )  # id: catalog wins (not in plan nullable set)
        assert decisions[1].nullable is True  # name: override (?)
        assert (
            decisions[2].nullable is True
        )  # email: plan wins (right side of left join)
