"""Shared types for the introspection layer.

Kept in a separate module to avoid circular imports between `plan.py`,
`nullability.py`, and `catalog.py`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParamInfo:
    """Metadata about a single parameter in a prepared statement."""

    name: str        # _1, _2, etc (positional)
    type_oid: int    # Postgres type OID


@dataclass(frozen=True)
class ColumnInfo:
    """Metadata about a single column in a query's result set.

    Sourced from the prepared-statement RowDescription that Postgres
    returns after Parse + Describe. asyncpg surfaces this via
    `stmt.get_attributes()`.

    Attributes:
        name: The column's name in the result set. This is the alias if
            the user wrote one, otherwise Postgres's chosen name. May
            still carry a trailing `!` or `?` override marker — the
            nullability module strips and consumes those.
        type_oid: The Postgres type OID. The renderer maps this to a
            Python type.
        table_oid: The OID of the underlying table the column came from,
            or 0 if the column is a computed expression with no single
            originating table (e.g. `a + b AS total`, `count(*)`).
        attr_number: The 1-based column index within the originating
            table. <= 0 means "no underlying column" — same semantics as
            table_oid == 0.
    """

    name: str
    type_oid: int
    table_oid: int
    attr_number: int
