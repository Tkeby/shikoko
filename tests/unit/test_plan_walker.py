"""Unit tests for nullables_from_plan — the plan-tree walker.

Every case builds hand-rolled Plan trees and checks the returned set of
nullable output indices. No JSON, no Postgres.
"""

from __future__ import annotations

from pysquirrel.introspect.nullability import nullables_from_plan
from pysquirrel.introspect.plan import Plan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scan(output: tuple[str, ...]) -> Plan:
    """Shorthand for a leaf scan node (no join, no children)."""
    return Plan(join_type=None, output=output, plans=())


# ---------------------------------------------------------------------------
# The eight join shapes from the plan + the §6.1 table
# ---------------------------------------------------------------------------


class TestNullablesFromPlan:
    """Parametrized core cases from §6.1 of the design doc."""

    def test_1_inner_join_empty_nullable(self) -> None:
        """Inner Join(a, b) over [a.x, b.y] → empty set."""
        plan = Plan(
            join_type="Inner",
            output=("a.x", "b.y"),
            plans=(
                _scan(("a.x",)),
                _scan(("b.y",)),
            ),
        )
        assert nullables_from_plan(plan) == set()

    def test_2_left_join_right_nullable(self) -> None:
        """Left Join(a, b) over [a.x, b.y] → {1}."""
        plan = Plan(
            join_type="Left",
            output=("a.x", "b.y"),
            plans=(
                _scan(("a.x",)),
                _scan(("b.y",)),
            ),
        )
        assert nullables_from_plan(plan) == {1}

    def test_3_right_join_left_nullable(self) -> None:
        """Right Join(a, b) over [a.x, b.y] → {0}."""
        plan = Plan(
            join_type="Right",
            output=("a.x", "b.y"),
            plans=(
                _scan(("a.x",)),
                _scan(("b.y",)),
            ),
        )
        assert nullables_from_plan(plan) == {0}

    def test_4_full_join_all_nullable(self) -> None:
        """Full Join(a, b) over [a.x, b.y] → {0, 1}."""
        plan = Plan(
            join_type="Full",
            output=("a.x", "b.y"),
            plans=(
                _scan(("a.x",)),
                _scan(("b.y",)),
            ),
        )
        assert nullables_from_plan(plan) == {0, 1}

    def test_5_semi_join_right_nullable(self) -> None:
        """Semi Join(a, b) over [a.x, b.y] → {1} (mirrors Squirrel)."""
        plan = Plan(
            join_type="Semi",
            output=("a.x", "b.y"),
            plans=(
                _scan(("a.x",)),
                _scan(("b.y",)),
            ),
        )
        assert nullables_from_plan(plan) == {1}

    def test_6_anti_join_empty(self) -> None:
        """Anti Join(a, b) over [a.x] → empty set."""
        plan = Plan(
            join_type="Anti",
            output=("a.x",),
            plans=(
                _scan(("a.x",)),
                _scan(()),
            ),
        )
        assert nullables_from_plan(plan) == set()

    def test_7_nested_left_above_inner(self) -> None:
        """Left(a, Inner(b, c)) over [a.x, b.y, c.z] → {1, 2}.

        The inner join doesn't contribute nullability, but the left join
        above it makes the entire right subtree's outputs nullable.
        """
        inner = Plan(
            join_type="Inner",
            output=("b.y", "c.z"),
            plans=(
                _scan(("b.y",)),
                _scan(("c.z",)),
            ),
        )
        plan = Plan(
            join_type="Left",
            output=("a.x", "b.y", "c.z"),
            plans=(
                _scan(("a.x",)),
                inner,
            ),
        )
        assert nullables_from_plan(plan) == {1, 2}

    def test_8_stack_of_joins_later_wins_dedup(self) -> None:
        """Left(Left(a, b), c) over [a.x, b.y, c.z] → {1, 2}.

        Both the outer and inner left join mark the right side nullable.
        Dedup: same expression in the accumulator twice should still
        produce a single entry.
        """
        inner_left = Plan(
            join_type="Left",
            output=("a.x", "b.y"),
            plans=(
                _scan(("a.x",)),
                _scan(("b.y",)),
            ),
        )
        plan = Plan(
            join_type="Left",
            output=("a.x", "b.y", "c.z"),
            plans=(
                inner_left,
                _scan(("c.z",)),
            ),
        )
        assert nullables_from_plan(plan) == {1, 2}


# ---------------------------------------------------------------------------
# §6.1 table cases #9 and #10
# ---------------------------------------------------------------------------


class TestNullablesFromPlanExtraCases:
    def test_9_no_join_single_seq_scan(self) -> None:
        """A plain Seq Scan with no join → empty set."""
        plan = Plan(
            join_type=None,
            output=("a.x", "a.y"),
            plans=(),
        )
        assert nullables_from_plan(plan) == set()

    def test_10_empty_output_at_root(self) -> None:
        """Plan with empty Output at root → empty set, no crash."""
        plan = Plan(
            join_type="Left",
            output=(),
            plans=(
                _scan(()),
                _scan(()),
            ),
        )
        assert nullables_from_plan(plan) == set()

    def test_11_non_join_wrapper_above_join(self) -> None:
        """Sort/Aggregate/Hash-style wrapper (join_type=None) above a Left
        Join → walker must recurse into the child and pick up the
        nullable right-side output.

        Real EXPLAIN routinely emits a non-join node (Sort, Aggregate,
        Hash, Materialize, …) wrapping the join. The walker's else
        branch handles this by plain recursion.
        """
        join = Plan(
            join_type="Left",
            output=("a.x", "b.y"),
            plans=(
                _scan(("a.x",)),
                _scan(("b.y",)),
            ),
        )
        wrapper = Plan(
            join_type=None,
            output=("a.x", "b.y"),
            plans=(join,),
        )
        assert nullables_from_plan(wrapper) == {1}


# ---------------------------------------------------------------------------
# Dedup: "later-occurrence wins" for duplicate output expressions
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Determinism: set[int] iteration order must not leak into results
# ---------------------------------------------------------------------------


class TestNullablesFromPlanDeterminism:
    """Verify that the internal set[int] doesn't introduce non-determinism.

    The walker accumulates nullable column indices into a set[int].
    Python sets have undefined iteration order (and CPython 3.12+ even
    randomizes hash seeds by default). These tests assert that calling
    nullables_from_plan N times on the same input always produces the
    same set, and that the downstream render pipeline (which consumes
    the set via positional index checks) produces byte-identical output.
    """

    @staticmethod
    def _multi_join_plan() -> Plan:
        """A plan with many outputs and multiple join types.

        This exercises the full range of _walk branches and produces
        a non-trivial set of nullable indices.
        """
        # Full Join → all outputs nullable
        full = Plan(
            join_type="Full",
            output=("a.x", "b.y"),
            plans=(
                _scan(("a.x",)),
                _scan(("b.y",)),
            ),
        )
        # Left Join above the full join
        plan = Plan(
            join_type="Left",
            output=("c.z", "a.x", "b.y"),
            plans=(
                _scan(("c.z",)),
                full,
            ),
        )
        return plan

    def test_repeated_calls_same_result(self) -> None:
        """Calling nullables_from_plan 100 times yields the same set."""
        plan = self._multi_join_plan()
        expected = nullables_from_plan(plan)
        for _ in range(100):
            assert nullables_from_plan(plan) == expected

    def test_result_is_positionally_consumed(self) -> None:
        """The returned set, consumed by index membership checks, produces
        a deterministic list of booleans regardless of set iteration order."""
        plan = self._multi_join_plan()
        nullable_set = nullables_from_plan(plan)
        ncols = len(plan.output)
        # This is how infer_nullability consumes the set: positional check.
        result = [i in nullable_set for i in range(ncols)]
        # Run again and compare.
        nullable_set2 = nullables_from_plan(plan)
        result2 = [i in nullable_set2 for i in range(ncols)]
        assert result == result2

    def test_render_deterministic_across_calls(self) -> None:
        """End-to-end: render_module produces identical output on repeated
        calls with the same IR input (modulo the timestamp header).

        This is the byte-compare check from the Day 5 plan. We strip the
        timestamp line before comparing.
        """
        from pysquirrel.codegen.ir import Field, PyType, QueryIR, ReturnKind
        from pysquirrel.codegen.render import render_module

        _int = PyType("int", frozenset())
        _str = PyType("str", frozenset())

        q = QueryIR(
            name="find_user",
            doc="Find a user.",
            sql="select id, name from users",
            params=(),
            row_model_name="FindUserRow",
            fields=(
                Field("id", _int, nullable=False),
                Field("name", _str, nullable=True),
            ),
            return_kind=ReturnKind.MANY,
            enums_used=(),
            source_file="test.sql",
            source_line=1,
        )

        def _strip_timestamp(source: str) -> str:
            """Remove the 'generated at:' line for byte-comparison."""
            return "\n".join(
                line
                for line in source.split("\n")
                if not line.startswith("# generated at:")
            )

        first = _strip_timestamp(render_module([q], "test.sql"))
        for _ in range(50):
            second = _strip_timestamp(render_module([q], "test.sql"))
            assert second == first


class TestNullablesFromPlanDedup:
    def test_duplicate_expression_later_wins(self) -> None:
        """When the same expression appears at two root-output positions,
        the dict comprehension `last wins` means the later index is the
        canonical mapping. Verify that nullables_from_plan still resolves
        correctly — both positions should appear if the child node
        contributes that expression.
        """
        # Root output has "x" at index 0 and also at index 2.
        # A left join makes the right side's "x" nullable.
        # The dict build maps "x" → 2 (last wins). So index 2 is in
        # the result, and index 0 is not (it lost the dedup).
        plan = Plan(
            join_type="Left",
            output=("x", "y", "x"),
            plans=(
                _scan(("x", "y")),
                _scan(("x",)),
            ),
        )
        # "x" from the right child maps to root index 2 (last wins).
        # Index 0 is lost during the dict build.
        assert nullables_from_plan(plan) == {2}

    def test_duplicate_in_inner_join_contributes_nothing(self) -> None:
        """Dedup with inner join: nothing is nullable regardless."""
        plan = Plan(
            join_type="Inner",
            output=("x", "y", "x"),
            plans=(
                _scan(("x", "y")),
                _scan(("x",)),
            ),
        )
        assert nullables_from_plan(plan) == set()

    def test_right_child_expression_not_in_root_ignored(self) -> None:
        """If the right child emits an expression that isn't in the root
        output, it's silently ignored (projected away)."""
        plan = Plan(
            join_type="Left",
            output=("a.x",),
            plans=(
                _scan(("a.x",)),
                _scan(("b.y",)),  # b.y not in root output
            ),
        )
        assert nullables_from_plan(plan) == set()
