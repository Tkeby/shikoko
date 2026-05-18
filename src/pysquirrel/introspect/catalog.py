"""Per-run cache for ``pg_type``, ``pg_enum``, and ``pg_attribute`` lookups.

The introspection pipeline hits these catalogs constantly — every column
checked for nullability needs a `pg_attribute` row, every non-builtin OID
needs a `pg_type` row, and every enum we render needs the variant list
from `pg_enum`. Doing the lookups uncached is fine on a small project
but quadratic on larger ones. A trivial dict cache scoped to a single
``generate`` run is enough.

Nothing here is concurrency-safe across event loops, but `generate`
runs sequentially against one connection, so that is not a concern.
"""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg


@dataclass(frozen=True)
class TypeInfo:
    """A subset of ``pg_type`` fields needed for type resolution."""

    oid: int
    typname: str
    typtype: str  # 'b'=base, 'e'=enum, 'c'=composite, 'd'=domain, 'r'=range, 'm'=multirange, 'p'=pseudo
    typelem: int  # element OID for array types, else 0
    typcategory: str  # 'A'=array, 'E'=enum, etc.
    schema: str  # namespace name (e.g. 'pg_catalog', 'public')


class CatalogCache:
    """In-memory cache of catalog rows for a single introspection run."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn
        self._types: dict[int, TypeInfo] = {}
        self._enum_labels: dict[int, tuple[str, ...]] = {}
        self._attnotnull: dict[tuple[int, int], bool] = {}

    async def type_info(self, oid: int) -> TypeInfo | None:
        """Return the cached ``pg_type`` row for *oid*, or None if missing."""
        cached = self._types.get(oid)
        if cached is not None:
            return cached

        row = await self._conn.fetchrow(
            """
            select
                t.oid,
                t.typname,
                t.typtype::text as typtype,
                t.typelem,
                t.typcategory::text as typcategory,
                n.nspname as schema
            from pg_type t
            join pg_namespace n on n.oid = t.typnamespace
            where t.oid = $1
            """,
            oid,
        )
        if row is None:
            return None

        info = TypeInfo(
            oid=row["oid"],
            typname=row["typname"],
            typtype=row["typtype"],
            typelem=row["typelem"],
            typcategory=row["typcategory"],
            schema=row["schema"],
        )
        self._types[oid] = info
        return info

    async def enum_labels(self, oid: int) -> tuple[str, ...]:
        """Return the enum variants for *oid* in sort order."""
        cached = self._enum_labels.get(oid)
        if cached is not None:
            return cached

        rows = await self._conn.fetch(
            """
            select enumlabel
            from pg_enum
            where enumtypid = $1
            order by enumsortorder
            """,
            oid,
        )
        labels = tuple(r["enumlabel"] for r in rows)
        self._enum_labels[oid] = labels
        return labels

    async def attnotnull(self, table_oid: int, attnum: int) -> bool:
        """Return True iff the column has a NOT NULL constraint.

        Missing rows (which should not happen for a column reported by
        Postgres in a RowDescription) default to False — i.e. nullable —
        which is the conservative choice.
        """
        key = (table_oid, attnum)
        if key in self._attnotnull:
            return self._attnotnull[key]

        row = await self._conn.fetchrow(
            "select attnotnull from pg_attribute where attrelid = $1 and attnum = $2",
            table_oid,
            attnum,
        )
        value = bool(row["attnotnull"]) if row is not None else False
        self._attnotnull[key] = value
        return value
