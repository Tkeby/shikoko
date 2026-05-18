"""Unit tests for shikoko.introspect.plan — JSON → Plan tree parsing."""

from __future__ import annotations

import pytest

from shikoko.introspect.plan import Plan, parse_plan_json

# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestParsePlanJsonHappyPath:
    def test_top_level_list_with_plan_envelope(self) -> None:
        """Standard EXPLAIN JSON shape: a list wrapping a dict with a "Plan" key."""
        payload = [
            {
                "Plan": {
                    "Node Type": "Seq Scan",
                    "Output": ["u.id", "u.email"],
                    "Plans": [],
                }
            }
        ]
        plan = parse_plan_json(payload)
        assert plan == Plan(
            join_type=None,
            output=("u.id", "u.email"),
            plans=(),
        )

    def test_already_unwrapped_dict(self) -> None:
        """Caller already peeled the outer list and "Plan" key."""
        payload = {
            "Node Type": "Hash Join",
            "Join Type": "Inner",
            "Output": ["a.x", "b.y"],
            "Plans": [
                {"Node Type": "Seq Scan", "Output": ["a.x"]},
                {"Node Type": "Seq Scan", "Output": ["b.y"]},
            ],
        }
        plan = parse_plan_json(payload)
        assert plan.join_type == "Inner"
        assert plan.output == ("a.x", "b.y")
        assert len(plan.plans) == 2

    def test_dict_with_plan_key(self) -> None:
        """A bare dict containing a "Plan" key (no outer list)."""
        payload = {
            "Plan": {
                "Node Type": "Seq Scan",
                "Output": ["x"],
            }
        }
        plan = parse_plan_json(payload)
        assert plan.output == ("x",)

    def test_nested_children(self) -> None:
        """Two levels of nesting: join over two scans."""
        payload = [
            {
                "Plan": {
                    "Node Type": "Hash Join",
                    "Join Type": "Left",
                    "Output": ["a.x", "b.y"],
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Output": ["a.x"],
                            "Plans": [],
                        },
                        {
                            "Node Type": "Seq Scan",
                            "Output": ["b.y"],
                            "Plans": [],
                        },
                    ],
                }
            }
        ]
        plan = parse_plan_json(payload)
        assert plan.join_type == "Left"
        assert plan.plans[0].join_type is None
        assert plan.plans[1].output == ("b.y",)


# ---------------------------------------------------------------------------
# Malformed payloads → ValueError
# ---------------------------------------------------------------------------


class TestParsePlanJsonMalformed:
    def test_empty_list(self) -> None:
        with pytest.raises(ValueError, match="empty list"):
            parse_plan_json([])

    def test_non_dict_top_level(self) -> None:
        with pytest.raises(ValueError, match="expected EXPLAIN root to be a dict"):
            parse_plan_json("not a dict")

    def test_plan_key_not_a_dict(self) -> None:
        with pytest.raises(ValueError, match="isn't a dict"):
            parse_plan_json([{"Plan": 42}])

    def test_output_not_a_list(self) -> None:
        with pytest.raises(ValueError, match="'Output' must be a list"):
            parse_plan_json([{"Plan": {"Output": "bad"}}])

    def test_plans_not_a_list(self) -> None:
        with pytest.raises(ValueError, match="'Plans' must be a list"):
            parse_plan_json([{"Plan": {"Plans": "bad"}}])


# ---------------------------------------------------------------------------
# Unknown Join Type → join_type = None (no crash)
# ---------------------------------------------------------------------------


class TestParsePlanJsonUnknownJoinType:
    def test_unknown_join_type_becomes_none(self) -> None:
        payload = [
            {
                "Plan": {
                    "Node Type": "Hash Join",
                    "Join Type": "Cross",
                    "Output": ["a.x"],
                }
            }
        ]
        plan = parse_plan_json(payload)
        assert plan.join_type is None

    def test_missing_join_type_is_none(self) -> None:
        payload = [{"Plan": {"Node Type": "Seq Scan", "Output": ["x"]}}]
        plan = parse_plan_json(payload)
        assert plan.join_type is None

    def test_empty_string_join_type_is_none(self) -> None:
        payload = [{"Plan": {"Join Type": "", "Output": ["x"]}}]
        plan = parse_plan_json(payload)
        assert plan.join_type is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestParsePlanJsonEdgeCases:
    def test_missing_output_gives_empty_tuple(self) -> None:
        payload = [{"Plan": {"Node Type": "Seq Scan"}}]
        plan = parse_plan_json(payload)
        assert plan.output == ()

    def test_null_output_gives_empty_tuple(self) -> None:
        payload = [{"Plan": {"Node Type": "Seq Scan", "Output": None}}]
        plan = parse_plan_json(payload)
        assert plan.output == ()

    def test_missing_plans_gives_empty_tuple(self) -> None:
        payload = [{"Plan": {"Node Type": "Seq Scan", "Output": ["x"]}}]
        plan = parse_plan_json(payload)
        assert plan.plans == ()

    def test_output_items_coerced_to_str(self) -> None:
        """If Postgres returns numeric output items, stringify them."""
        payload = [{"Plan": {"Output": [1, 2, 3]}}]
        plan = parse_plan_json(payload)
        assert plan.output == ("1", "2", "3")
