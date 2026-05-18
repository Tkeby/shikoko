"""Postgres enum discovery and Python identifier rendering.

Postgres enum OIDs are user-assigned, so they cannot be hardcoded the
way built-in scalar OIDs are. The flow is:

    1. The type resolver sees a non-builtin OID with ``kind='scalar'``.
    2. It asks the catalog cache whether the OID's ``typtype`` is ``'e'``.
    3. If yes, it asks for the variant labels (already cached after the
       first hit).
    4. It builds an :class:`~pysquirrel.codegen.ir.EnumIR` and stashes
       it on the resolver so the renderer can emit it.

The Python identifiers we emit follow standard PEP 8 enum-member style:
upper-snake-case derived from the Postgres label. Non-identifier
characters are replaced with ``_``; labels starting with a digit get a
leading ``_``; collisions get numeric suffixes.
"""

from __future__ import annotations

import re

from pysquirrel.codegen.ir import EnumIR
from pysquirrel.codegen.naming import to_pascal_case

__all__ = [
    "enum_py_name",
    "enum_member_name",
    "build_enum_ir",
]


_NON_IDENT = re.compile(r"[^0-9A-Za-z_]+")
_LEADING_DIGIT = re.compile(r"^[0-9]")


def enum_py_name(pg_name: str) -> str:
    """Convert a Postgres enum type name to a Python class name (PascalCase)."""
    # Squirrel does not pluralise or otherwise mangle: `mood` -> `Mood`,
    # `user_status` -> `UserStatus`.
    return to_pascal_case(pg_name)


def enum_member_name(label: str) -> str:
    """Convert a Postgres enum label to a Python enum member name.

    Strategy: replace runs of non-identifier characters with a single
    underscore, uppercase, and prefix with ``_`` if the result starts
    with a digit. If the result is empty (label was all punctuation),
    fall back to ``MEMBER``.
    """
    cleaned = _NON_IDENT.sub("_", label).strip("_")
    if not cleaned:
        return "MEMBER"
    if _LEADING_DIGIT.match(cleaned):
        cleaned = f"_{cleaned}"
    return cleaned.upper()


def build_enum_ir(pg_name: str, labels: tuple[str, ...]) -> EnumIR:
    """Construct an :class:`EnumIR` from a Postgres enum name and label list.

    Collisions between rendered member names (after normalisation) are
    resolved by appending an ``_2``, ``_3``, ... suffix to the second
    and later occurrences, in label order.
    """
    seen: dict[str, int] = {}
    variants: list[tuple[str, str]] = []
    for label in labels:
        member = enum_member_name(label)
        count = seen.get(member, 0) + 1
        seen[member] = count
        if count > 1:
            member = f"{member}_{count}"
        variants.append((member, label))

    return EnumIR(
        py_name=enum_py_name(pg_name),
        pg_name=pg_name,
        variants=tuple(variants),
    )
