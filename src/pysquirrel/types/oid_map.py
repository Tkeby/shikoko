"""Map Postgres type OIDs to :class:`PyType` instances.

OIDs for built-in types are stable across Postgres versions, so we
hardcode them here rather than querying ``pg_type`` every run. The list
mirrors the values in ``src/include/catalog/pg_type.dat`` from the
Postgres source tree.

Array OIDs are also stable for the built-ins and are listed in their own
table — for less common arrays (or arrays of user-defined types like
enums), the caller is expected to look up ``pg_type.typelem`` via the
catalog cache and recursively resolve.
"""

from __future__ import annotations

from pathlib import Path

from pysquirrel.codegen.ir import PyType
from pysquirrel.errors import UnsupportedTypeError

# Imports we reuse across multiple PyType entries.
_DATETIME_IMPORT = frozenset({"from datetime import datetime"})
_DATE_IMPORT = frozenset({"from datetime import date"})
_TIME_IMPORT = frozenset({"from datetime import time"})
_TIMEDELTA_IMPORT = frozenset({"from datetime import timedelta"})
_DECIMAL_IMPORT = frozenset({"from decimal import Decimal"})
_UUID_IMPORT = frozenset({"from uuid import UUID"})
_ANY_IMPORT = frozenset({"from typing import Any"})
_IPV4ADDR_IMPORT = frozenset({"from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network"})


# OIDs from src/include/catalog/pg_type.dat in Postgres source.
BUILTIN_OIDS: dict[int, PyType] = {
    # --- Boolean ---
    16:   PyType("bool", frozenset()),

    # --- Bytea ---
    17:   PyType("bytes", frozenset()),

    # --- Integers ---
    20:   PyType("int", frozenset()),         # int8 (bigint)
    21:   PyType("int", frozenset()),         # int2 (smallint)
    23:   PyType("int", frozenset()),         # int4 (integer)
    26:   PyType("int", frozenset()),         # oid

    # --- Floats ---
    700:  PyType("float", frozenset()),       # float4 (real)
    701:  PyType("float", frozenset()),       # float8 (double precision)

    # --- Numeric / decimal ---
    1700: PyType("Decimal", _DECIMAL_IMPORT),

    # --- Money: asyncpg returns this as str ---
    790:  PyType("str", frozenset()),

    # --- Text / character types ---
    18:   PyType("str", frozenset()),         # char
    19:   PyType("str", frozenset()),         # name
    25:   PyType("str", frozenset()),         # text
    1042: PyType("str", frozenset()),         # bpchar (char(n))
    1043: PyType("str", frozenset()),         # varchar

    # --- Date / time ---
    1082: PyType("date", _DATE_IMPORT),
    1083: PyType("time", _TIME_IMPORT),
    1114: PyType("datetime", _DATETIME_IMPORT),       # timestamp
    1184: PyType("datetime", _DATETIME_IMPORT),       # timestamptz
    1186: PyType("timedelta", _TIMEDELTA_IMPORT),     # interval
    1266: PyType("time", _TIME_IMPORT),               # timetz

    # --- UUID ---
    2950: PyType("UUID", _UUID_IMPORT),

    # --- JSON ---
    114:  PyType("Any", _ANY_IMPORT),         # json
    3802: PyType("Any", _ANY_IMPORT),         # jsonb

    # --- XML ---
    142:  PyType("str", frozenset()),

    # --- Network address types — asyncpg returns ipaddress objects ---
    869:  PyType(
        "IPv4Address | IPv6Address",
        _IPV4ADDR_IMPORT,
    ),  # inet
    650:  PyType(
        "IPv4Network | IPv6Network",
        _IPV4ADDR_IMPORT,
    ),  # cidr
    829:  PyType("str", frozenset()),         # macaddr
    774:  PyType("str", frozenset()),         # macaddr8

    # --- Bit strings ---
    1560: PyType("str", frozenset()),         # bit
    1562: PyType("str", frozenset()),         # varbit
}


# Built-in array OIDs → element OID. For user-defined arrays (e.g. enum[])
# the caller should fall back to ``pg_type.typelem`` via the catalog cache.
_BUILTIN_ARRAY_OIDS: dict[int, int] = {
    1000: 16,    # bool[]
    1001: 17,    # bytea[]
    1002: 18,    # char[]
    1003: 19,    # name[]
    1005: 21,    # int2[]
    1007: 23,    # int4[]
    1009: 25,    # text[]
    1014: 1042,  # bpchar[]
    1015: 1043,  # varchar[]
    1016: 20,    # int8[]
    1021: 700,   # float4[]
    1022: 701,   # float8[]
    1028: 26,    # oid[]
    1040: 829,   # macaddr[]
    1041: 869,   # inet[]
    651:  650,   # cidr[]
    775:  774,   # macaddr8[]
    143:  142,   # xml[]
    199:  114,   # json[]
    3807: 3802,  # jsonb[]
    1115: 1114,  # timestamp[]
    1182: 1082,  # date[]
    1183: 1083,  # time[]
    1185: 1184,  # timestamptz[]
    1187: 1186,  # interval[]
    1270: 1266,  # timetz[]
    1231: 1700,  # numeric[]
    791:  790,   # money[]
    1561: 1560,  # bit[]
    1563: 1562,  # varbit[]
    2951: 2950,  # uuid[]
}


def is_array_oid(oid: int) -> int | None:
    """Return the element OID if *oid* is a known built-in array OID, else None.

    For unknown array OIDs (typically arrays of user-defined types), the
    caller should query ``pg_type.typelem`` via the catalog cache.
    """
    return _BUILTIN_ARRAY_OIDS.get(oid)


def resolve_builtin(oid: int) -> PyType | None:
    """Look up *oid* in the built-in scalar table. Returns None if not found."""
    return BUILTIN_OIDS.get(oid)


def wrap_array(elem_type: PyType) -> PyType:
    """Wrap *elem_type* in ``list[...]`` while preserving its imports."""
    return PyType(annotation=f"list[{elem_type.annotation}]", imports=elem_type.imports)


def resolve_type(oid: int, type_name: str, kind: str) -> PyType:
    """Map a Postgres OID to a :class:`PyType` — scalars + built-in arrays only.

    This is the synchronous, catalog-free entry point that exists for
    callers that don't need enum or user-defined-array support (mostly
    tests). For full support including enums, use
    :class:`pysquirrel.introspect.prepare.TypeResolver`.

    Args:
        oid: The Postgres type OID. For arrays this is the array OID
            (e.g. 1007 for ``int4[]``).
        type_name: Type name from Postgres, used in error messages.
        kind: ``'scalar'``, ``'array'``, or other asyncpg type kinds.

    Returns:
        The resolved :class:`PyType`.

    Raises:
        UnsupportedTypeError: if the OID is not in the built-in table.
    """
    if kind == "array":
        elem_oid = is_array_oid(oid)
        if elem_oid is None:
            raise UnsupportedTypeError(
                file=Path("<introspection>"),
                oid=oid,
                pg_type_name=type_name,
            )
        elem_type = resolve_builtin(elem_oid)
        if elem_type is None:
            raise UnsupportedTypeError(
                file=Path("<introspection>"),
                oid=elem_oid,
                pg_type_name=type_name,
            )
        return wrap_array(elem_type)

    py_type = resolve_builtin(oid)
    if py_type is None:
        raise UnsupportedTypeError(
            file=Path("<introspection>"),
            oid=oid,
            pg_type_name=type_name,
        )
    return py_type
