# Type Mapping

shikoko introspects your Postgres schema and generates Python type
annotations that reflect the real column types. This document describes
every supported mapping, how array and enum types are handled, how
nullability is expressed, and what happens when shikoko encounters a
type it cannot map.

The authoritative source for the OID-to-Python mapping lives in
`src/shikoko/types/oid_map.py`. This document is the human-readable
counterpart.

---

## Scalar type mappings

The table below covers every built-in Postgres type that shikoko
maps. OIDs are stable across Postgres versions, so these are hardcoded
rather than queried from `pg_type` at runtime.

### Boolean

| OID | Postgres type | Python type | Import |
|-----|---------------|-------------|--------|
| 16 | `bool` | `bool` | — |

### Integers

| OID | Postgres type | Python type | Import |
|-----|---------------|-------------|--------|
| 20 | `int8` (`bigint`) | `int` | — |
| 21 | `int2` (`smallint`) | `int` | — |
| 23 | `int4` (`integer`) | `int` | — |
| 26 | `oid` | `int` | — |

### Floating-point

| OID | Postgres type | Python type | Import |
|-----|---------------|-------------|--------|
| 700 | `float4` (`real`) | `float` | — |
| 701 | `float8` (`double precision`) | `float` | — |

### Numeric / decimal

| OID | Postgres type | Python type | Import |
|-----|---------------|-------------|--------|
| 1700 | `numeric` | `Decimal` | `from decimal import Decimal` |

### Money

| OID | Postgres type | Python type | Import |
|-----|---------------|-------------|--------|
| 790 | `money` | `str` | — |

### Text / character types

| OID | Postgres type | Python type | Import |
|-----|---------------|-------------|--------|
| 18 | `char` | `str` | — |
| 19 | `name` | `str` | — |
| 25 | `text` | `str` | — |
| 1042 | `bpchar` (`char(n)`) | `str` | — |
| 1043 | `varchar` | `str` | — |

### Date / time

| OID | Postgres type | Python type | Import |
|-----|---------------|-------------|--------|
| 1082 | `date` | `date` | `from datetime import date` |
| 1083 | `time` | `time` | `from datetime import time` |
| 1114 | `timestamp` | `datetime` | `from datetime import datetime` |
| 1184 | `timestamptz` | `datetime` | `from datetime import datetime` |
| 1186 | `interval` | `timedelta` | `from datetime import timedelta` |
| 1266 | `timetz` | `time` | `from datetime import time` |

### UUID

| OID | Postgres type | Python type | Import |
|-----|---------------|-------------|--------|
| 2950 | `uuid` | `UUID` | `from uuid import UUID` |

### JSON

| OID | Postgres type | Python type | Import |
|-----|---------------|-------------|--------|
| 114 | `json` | `Any` | `from typing import Any` |
| 3802 | `jsonb` | `Any` | `from typing import Any` |

JSON columns are typed as `Any` because their structure is not
constrained by the database. If you need stricter typing, use
`extra_claims` or a custom Pydantic model to validate the value at
runtime.

### Network address types

| OID | Postgres type | Python type | Import |
|-----|---------------|-------------|--------|
| 869 | `inet` | `IPv4Address \| IPv6Address` | `from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network` |
| 650 | `cidr` | `IPv4Network \| IPv6Network` | `from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network` |
| 829 | `macaddr` | `str` | — |
| 774 | `macaddr8` | `str` | — |

The `inet` and `cidr` types use the `ipaddress` module because
asyncpg natively returns `ipaddress` objects. The import includes all
four names so that a single import line covers both the address and
network variants.

### Bit strings

| OID | Postgres type | Python type | Import |
|-----|---------------|-------------|--------|
| 1560 | `bit` | `str` | — |
| 1562 | `varbit` | `str` | — |

### XML

| OID | Postgres type | Python type | Import |
|-----|---------------|-------------|--------|
| 142 | `xml` | `str` | — |

### Binary

| OID | Postgres type | Python type | Import |
|-----|---------------|-------------|--------|
| 17 | `bytea` | `bytes` | — |

---

## Array types

Every built-in scalar type has a corresponding array type with a stable
OID. Arrays are mapped to `list[T]` where `T` is the element type from
the scalar table above.

| Array OID | Element OID | Postgres type | Python type |
|-----------|-------------|---------------|-------------|
| 1000 | 16 | `bool[]` | `list[bool]` |
| 1001 | 17 | `bytea[]` | `list[bytes]` |
| 1002 | 18 | `char[]` | `list[str]` |
| 1003 | 19 | `name[]` | `list[str]` |
| 1005 | 21 | `int2[]` | `list[int]` |
| 1007 | 23 | `int4[]` | `list[int]` |
| 1016 | 20 | `int8[]` | `list[int]` |
| 1028 | 26 | `oid[]` | `list[int]` |
| 1021 | 700 | `float4[]` | `list[float]` |
| 1022 | 701 | `float8[]` | `list[float]` |
| 1231 | 1700 | `numeric[]` | `list[Decimal]` |
| 791 | 790 | `money[]` | `list[str]` |
| 1009 | 25 | `text[]` | `list[str]` |
| 1014 | 1042 | `bpchar[]` | `list[str]` |
| 1015 | 1043 | `varchar[]` | `list[str]` |
| 1182 | 1082 | `date[]` | `list[date]` |
| 1183 | 1083 | `time[]` | `list[time]` |
| 1115 | 1114 | `timestamp[]` | `list[datetime]` |
| 1185 | 1184 | `timestamptz[]` | `list[datetime]` |
| 1187 | 1186 | `interval[]` | `list[timedelta]` |
| 1270 | 1266 | `timetz[]` | `list[time]` |
| 2951 | 2950 | `uuid[]` | `list[UUID]` |
| 199 | 114 | `json[]` | `list[Any]` |
| 3807 | 3802 | `jsonb[]` | `list[Any]` |
| 143 | 142 | `xml[]` | `list[str]` |
| 1041 | 869 | `inet[]` | `list[IPv4Address \| IPv6Address]` |
| 651 | 650 | `cidr[]` | `list[IPv4Network \| IPv6Network]` |
| 1040 | 829 | `macaddr[]` | `list[str]` |
| 775 | 774 | `macaddr8[]` | `list[str]` |
| 1561 | 1560 | `bit[]` | `list[str]` |
| 1563 | 1562 | `varbit[]` | `list[str]` |

For arrays of user-defined types (for example, `my_enum[]`), shikoko
queries `pg_type.typelem` via the catalog cache and recursively resolves
the element type. The array is then wrapped in `list[...]` the same way.
This is handled automatically by `TypeResolver` in
`src/shikoko/introspect/prepare.py`.

---

## Enum types

Postgres enums are mapped to Python `StrEnum` classes. For example,
given this DDL:

```sql
CREATE TYPE mood AS ENUM ('sad', 'ok', 'happy');
```

shikoko generates:

```python
class Mood(StrEnum):
    SAD = 'sad'
    OK = 'ok'
    HAPPY = 'happy'
```

### Naming rules

**Class name:** The Postgres enum type name is converted to PascalCase.
For example, `user_status` becomes `UserStatus`. The conversion uses
`to_pascal_case` from `src/shikoko/codegen/naming.py` — no
pluralisation or other mangling is applied.

**Member names:** Each Postgres enum label is converted to an
upper-snake-case Python identifier by the `enum_member_name` function in
`src/shikoko/types/enums.py`. The rules are:

1. Runs of non-identifier characters (`[^0-9A-Za-z_]`) are replaced
   with a single underscore.
2. Leading and trailing underscores are stripped.
3. If the result is empty (the label was entirely non-identifier
   characters), the member name falls back to `MEMBER`.
4. If the result starts with a digit, a leading underscore is
   prepended.
5. The result is uppercased.

**Collision handling:** If two labels normalise to the same member name,
the second and subsequent occurrences get a numeric suffix (`_2`, `_3`,
...) in label order. For example:

```sql
CREATE TYPE confusing AS ENUM ('foo-bar', 'foo_bar', 'foo bar');
```

All three labels normalise to `FOO_BAR`, producing:

```python
class Confusing(StrEnum):
    FOO_BAR = 'foo-bar'
    FOO_BAR_2 = 'foo_bar'
    FOO_BAR_3 = 'foo bar'
```

### Deduplication

Enums are deduplicated by their Postgres type name. If two queries
reference the same `mood` enum, only one `Mood` class is emitted in the
generated module. This is handled by `TypeResolver`, which accumulates
enum definitions keyed by OID.

### Resolution

Enum type OIDs are user-assigned, so they cannot be hardcoded. When
shikoko encounters a non-builtin scalar OID, it queries
`pg_type.typtype`. If the value is `'e'`, it fetches the labels from
`pg_enum` (ordered by `enumsortorder`) and builds a `StrEnum` class.

---

## Nullability

Each column in a generated row model is annotated for nullability:

- **Non-nullable columns** render as `field_name: T`
- **Nullable columns** render as `field_name: T | None = None`

Nullability is inferred from three sources in priority order:

1. **Explicit overrides** — Append `!` (force non-null) or `?` (force
   nullable) to the column alias in your SQL. See
   [annotations.md](annotations.md) for full details.
2. **EXPLAIN plan walker** — shikoko analyses the query plan to
   detect columns that can be null due to outer joins.
3. **`pg_attribute.attnotnull`** — the Postgres catalog `NOT NULL`
   constraint.

See [annotations.md](annotations.md) for examples of the `!` and `?`
overrides.

---

## Unsupported types

When shikoko encounters a Postgres type that is not in the built-in
OID table and is not an enum, it raises
`UnsupportedTypeError` at code-generation time:

```
<introspection>: unsupported type my_composite (oid 12345)
```

This is a compile-time error — it will not surface at runtime. The
following Postgres type categories are **not supported** in the current
version:

| `typtype` | Category | Status |
|-----------|----------|--------|
| `b` (base) | Built-in | Supported if OID is in the hardcoded table |
| `e` (enum) | Enum | Supported |
| `A` (array) | Array | Supported for built-in and user-defined element types |
| `c` (composite) | Composite/row | Not supported |
| `d` (domain) | Domain | Not supported |
| `r` (range) | Range | Not supported |
| `m` (multirange) | Multirange | Not supported |
| `p` (pseudo) | Pseudo-types | Not supported |

If you need one of these types, open an issue or wrap the column in a
cast to a supported type in your query (e.g. `my_col::text`).

---

## The role of asyncpg

shikoko generates **static type annotations** — it does not perform
runtime type conversion itself. The actual conversion from Postgres
wire-format values to Python objects is handled by **asyncpg**, the
database driver.

This means:

- The Python types listed in the tables above are exactly what asyncpg
  returns at runtime. For example, asyncpg returns `datetime` objects
  for `timestamptz` columns, so shikoko annotates them as
  `datetime`.
- shikoko's job is to know the mapping ahead of time (from the OID)
  so it can emit correct annotations and import statements in the
  generated code, without needing to execute the query first.
- If asyncpg changes its return types in a future version, the mapping
  in `src/shikoko/types/oid_map.py` would need to be updated to
  match. In practice these mappings are very stable.

### How resolution works at a high level

```
SQL query column
  │
  ▼
Postgres OID (from asyncpg result metadata)
  │
  ├── Built-in scalar? ──► Hardcoded OID table → PyType
  │
  ├── Built-in array? ──► Hardcoded array-OID → element-OID lookup
  │                        → resolve element → list[PyType]
  │
  ├── Unknown array? ──► pg_type.typelem (catalog cache)
  │                      → recursive element resolution → list[PyType]
  │
  ├── Enum? ──► pg_type.typtype == 'e' → pg_enum labels → StrEnum class
  │
  └── None of the above ──► UnsupportedTypeError
```

The fast path (built-in scalars and arrays) requires no database
queries at all. Only enums and user-defined arrays trigger catalog
lookups, and those are cached for the duration of the introspection
run.
