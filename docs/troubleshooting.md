# Troubleshooting

This guide covers the most common errors and issues encountered when using
pysquirrel, along with their causes and fixes.

---

## Quick error reference

| Error message or class | Likely cause | Fix |
|---|---|---|
| `QueryParseError: file contains no SQL statement` | `.sql` file has only comments or is empty | Add a SQL statement after the comment block |
| `UnknownAnnotationError: unknown annotation: X` | Misspelled or unsupported `-- @` annotation | Use only `@one`, `@exec`, or `name:` — see [annotations.md](annotations.md) |
| `UnsupportedTypeError: unsupported type NAME (oid NNN)` | Postgres type is not in the built-in OID map (composite, domain, range, etc.) | Cast the column to a supported type, e.g. `my_col::text` |
| `IntrospectionError: introspection failed: …` | Query references a nonexistent table, function, or column, or Postgres rejected the statement | Verify the SQL runs in `psql` with the same database and role |
| `ConfigError: Invalid DATABASE_URL: …` | Connection string does not start with `postgresql://` | Pass a valid DSN, e.g. `postgresql://user:pass@host:5432/dbname` |
| `Error: no database name resolved` | No `--database-url`, `DATABASE_URL`, `PGDATABASE`, or `pyproject.toml` project name | Pass `--database-url` or set `DATABASE_URL` |
| `No .sql files found under any sql/ directory` | No `sql/` directory exists, or `.sql` files are in nested subdirectories | Place `.sql` files directly inside a directory named `sql/` |
| `ruff not found on PATH` warning | `ruff` is not installed | Install with `pip install ruff` — or ignore it (formatting is cosmetic) |
| `ImportError` when importing generated code | `asyncpg` or `pydantic` not installed at runtime | `pip install asyncpg pydantic` |

---

## Detailed sections

### 1. No SQL files found

**Message:**

```
No .sql files found under any sql/ directory.
```

**Cause:** pysquirrel recursively searches your project root for directories
literally named `sql/` and looks for `.sql` files **directly** inside them.
Files nested in subdirectories of `sql/` (such as `sql/queries/list_users.sql`)
are **not** discovered.

**Fix:** Place your `.sql` files directly inside a `sql/` directory:

```
my_project/
├── sql/
│   ├── list_users.sql      # discovered
│   └── create_user.sql     # discovered
├── sql_generated.py
└── pyproject.toml
```

If you need multiple groups of queries, use multiple `sql/` directories at
different levels of your project:

```
my_project/
├── app/
│   └── sql/
│       └── list_users.sql
├── billing/
│   └── sql/
│       └── get_invoices.sql
```

Each `sql/` directory produces its own `sql_generated.py` in the parent
directory.

---

### 2. No database name resolved

**Message:**

```
Error: no database name resolved. Use --database-url, set DATABASE_URL,
PGDATABASE, or run from a directory with a pyproject.toml.
```

**Cause:** pysquirrel could not determine which database to connect to. The
database name is resolved through the following precedence chain:

1. `--database-url` CLI flag
2. `DATABASE_URL` environment variable
3. `PGDATABASE` environment variable
4. `[project].name` from `pyproject.toml` (hyphens replaced with underscores)
5. Current working directory name

If none of these provide a database name, pysquirrel exits with this error.

**Fix:** Use any one of these approaches:

```bash
# Option A: pass the full DSN
pysquirrel generate --database-url postgresql://user:pass@localhost:5432/mydb

# Option B: set the environment variable
export DATABASE_URL=postgresql://user:pass@localhost:5432/mydb
pysquirrel generate

# Option C: use libpq-style env vars
export PGDATABASE=mydb
pysquirrel generate

# Option D: rely on pyproject.toml
# With [project] name = "mydb" in pyproject.toml, pysquirrel uses "mydb"
```

---

### 3. Connection refused or failed

**Message (varies):**

```
<introspection>: introspection failed: could not connect to localhost:5432/mydb: ...
```

Or a raw asyncpg connection error.

**Cause:** pysquirrel cannot reach the Postgres server. Common reasons:

- Postgres is not running
- Wrong host or port
- Firewall or network issue
- Authentication failure (wrong user/password)
- SSL requirement mismatch

**Fix:**

1. Verify Postgres is running:
   ```bash
   pg_isready -h localhost -p 5432
   ```

2. Confirm you can connect with the same DSN using `psql`:
   ```bash
   psql "postgresql://user:pass@localhost:5432/mydb"
   ```

3. If `psql` fails too, the problem is outside pysquirrel — fix your Postgres
   configuration, credentials, or network first.

4. If you are using Docker, make sure the port is published (`-p 5432:5432`)
   and the container is healthy.

**Note on Postgres version:** pysquirrel requires PostgreSQL 16 or later
because it uses `EXPLAIN (FORMAT JSON, VERBOSE, GENERIC_PLAN)`. Connecting to
an older server produces:

```
<introspection>: introspection failed: PostgreSQL 15 is not supported;
pysquirrel requires PostgreSQL 16 or later (server_version_num=150000)
```

---

### 4. Unsupported type error

**Message:**

```
<introspection>: unsupported type my_composite (oid 12345)
```

**Cause:** The query selects a column whose Postgres type is not in pysquirrel's
built-in OID map and is not an enum. The following type categories are **not
supported**:

| `pg_type.typtype` | Category | Example |
|---|---|---|
| `c` | Composite (row type) | `CREATE TYPE address AS (...)` |
| `d` | Domain | `CREATE DOMAIN email AS text CHECK (...)` |
| `r` | Range | `int4range`, `tstzrange` |
| `m` | Multirange | `int4multirange` |
| `p` | Pseudo-type | `record`, `void`, `trigger` |

**Supported types** include: `bool`, `int2`/`int4`/`int8`/`oid`, `float4`/`float8`,
`numeric`, `text`/`varchar`/`bpchar`/`char`/`name`, `date`, `time`/`timetz`,
`timestamp`/`timestamptz`, `interval`, `uuid`, `json`/`jsonb`, `bytea`,
`inet`, `cidr`, `macaddr`/`macaddr8`, `xml`, `bit`/`varbit`, `money`,
all arrays of the above, and user-defined enums. See
[type-mapping.md](type-mapping.md) for the full table.

**Fix:** Cast unsupported columns to a supported type in your SQL:

```sql
-- Cast a composite column to text
select id, address::text as address from users;

-- Cast a domain to its base type
select id, email::text as email from users;

-- Cast a range to text
select id, active_period::text as active_period from subscriptions;
```

For the specific case of Postgres enums, pysquirrel handles them automatically
— no cast is needed.

---

### 5. Generated file has wrong nullability

**Symptom:** A generated field is typed as `str | None = None` when it should
be `str`, or vice versa.

**Cause:** Nullability inference uses the `EXPLAIN` plan (to detect outer-join
nullability) and `pg_attribute.attnotnull` (catalog `NOT NULL` constraints).
This algorithm is conservative — when in doubt, it marks a column as nullable.
Computed expressions with no originating table always default to nullable.

**Fix:** Add an explicit override to the column alias in your SQL:

- Append `!` to force non-null: `select u.email! from ...`
- Append `?` to force nullable: `select u.avatar_url? from ...`

The override marker is stripped from the Python field name. See
[annotations.md](annotations.md) for details.

```sql
-- Example: force email to be non-null despite the left join
select
    o.id,
    u.email!
from orders o
left join users u on u.id = o.user_id;
```

---

### 6. `pysquirrel check` fails in CI but works locally

**Symptom:** `pysquirrel check` exits with code 1 in CI, showing diffs, but
passes on your local machine.

**Cause:** The most likely cause is a different database schema between your
local Postgres and the CI database. pysquirrel introspects the live database,
so the generated code reflects the schema it sees — column types, nullability
constraints, and enum definitions all come from the database catalog.

If the `.sql` files have not changed (same content, same paths), the hash
short-circuit in `pysquirrel check` kicks in and no database query is needed.
If the files *have* changed (or are new), pysquirrel queries the database,
and any schema difference will produce different output.

**Fix:**

- Ensure CI uses the same schema as your local database. Apply migrations
  before running `pysquirrel check` in CI.
- The hash short-circuit means if `.sql` files haven't changed, the database
  isn't queried at all — so a schema mismatch only matters when `.sql` files
  change.
- If you want to verify the CI database schema is correct, connect directly:
  ```bash
  psql "$DATABASE_URL" -c "\d users"
  ```

---

### 7. ruff format not found

**Message (logged as warning):**

```
ruff not found on PATH; returning unformatted output
```

**Cause:** pysquirrel pipes generated Python source through `ruff format` for
consistent formatting. If `ruff` is not on `PATH`, the unformatted source is
written instead.

**Effect:** The generated file is functional but may have inconsistent
formatting (indentation, line breaks, etc.).

**Fix:**

```bash
pip install ruff
```

This is cosmetic only — the generated code works identically with or without
`ruff`. If you prefer not to install it, you can run a formatter separately
after generation.

---

### 8. Import errors when using generated code

**Message:**

```
ModuleNotFoundError: No module named 'asyncpg'
```

or

```
ModuleNotFoundError: No module named 'pydantic'
```

**Cause:** Generated modules import `asyncpg` and `pydantic` at the top level.
These must be installed in the environment where the generated code runs.
pysquirrel itself is only needed at code-generation time, not at runtime.

**Fix:**

```bash
pip install asyncpg pydantic
```

Add these to your project's runtime dependencies (e.g. in `pyproject.toml`
under `[project] dependencies`).

---

### 9. Enum class naming collisions

**Symptom:** Two enum members in the same Postgres enum type produce Python
identifiers that look like they would collide, but the generated code works.

**Cause:** pysquirrel normalizes Postgres enum labels to upper-snake-case
Python identifiers. If two labels normalize to the same identifier, pysquirrel
appends a numeric suffix (`_2`, `_3`, ...) to the second and subsequent
collisions.

**Example:** Given this DDL:

```sql
CREATE TYPE confusing AS ENUM ('foo-bar', 'foo_bar', 'foo bar');
```

All three labels normalize to `FOO_BAR`. pysquirrel generates:

```python
class Confusing(StrEnum):
    FOO_BAR = 'foo-bar'
    FOO_BAR_2 = 'foo_bar'
    FOO_BAR_3 = 'foo bar'
```

**Fix:** No action needed — pysquirrel handles this automatically. If the
resulting names are confusing, consider renaming the Postgres enum labels to
avoid ambiguity.

---

### 10. DO blocks and multi-statement SQL

**Symptom:** All columns in the generated row model are typed as nullable
(`T | None = None`) when using a `DO` block, multi-statement body, or other
utility command.

**Cause:** pysquirrel runs `EXPLAIN (FORMAT JSON, VERBOSE, GENERIC_PLAN)` on
each query to infer nullability. Postgres refuses to plan `DO` blocks and
multi-statement bodies (returning SQLSTATE `0A000` or `42601`). When `EXPLAIN`
fails, pysquirrel falls back to treating every column as nullable — this is
the conservative default.

**Fix:**

- Split multi-statement bodies into individual `.sql` files, each containing
  a single query.
- For `DO` blocks, consider whether a PL/pgSQL function is a better fit.
  pysquirrel is designed for `SELECT`, `INSERT ... RETURNING`, `UPDATE ...
  RETURNING`, and `DELETE ... RETURNING` — not for anonymous blocks.
- Use explicit `!` overrides to force non-nullable columns:
  ```sql
  select id!, name! from ...
  ```

---

### 11. Generic plan errors

**Symptom:** Columns that should be non-nullable are typed as nullable, and
no other cause applies.

**Cause:** pysquirrel uses `GENERIC_PLAN` (Postgres 16+) to avoid needing
concrete parameter values. Some SQL constructs fail under `GENERIC_PLAN` —
for example, CTEs that reference parameters in ways the planner cannot
generalize. When this happens, pysquirrel falls back gracefully: the plan is
`None`, and all columns default to nullable.

**Fix:** This is handled automatically by pysquirrel. If the resulting
nullability is too conservative, add `!` overrides to the affected columns.

---

### 12. Generated file changes between runs with no SQL changes

**Symptom:** Running `pysquirrel generate` twice produces different output
even though no `.sql` files changed.

**Cause — timestamp header:** The generated file includes a `# generated at:`
header with a UTC timestamp. This changes on every run, but `pysquirrel check`
ignores it (it compares content after regeneration, and the hash short-circuit
prevents regeneration when sources have not changed).

**Cause — actual code changes:** If the generated Python code itself differs
between runs (not just the timestamp), check for:

- **Non-deterministic ordering:** pysquirrel sorts queries alphabetically by
  name, so this should not happen. If it does, it is a bug — please file an
  issue.
- **Database schema changes:** If someone altered a table, enum, or constraint
  between runs, the generated code will reflect the new schema.
- **Enum label ordering:** pysquirrel uses `enumsortorder` from `pg_enum`,
  which is stable — so this should not cause differences.

**Fix:** If only the timestamp differs, this is expected and harmless. If the
actual code differs, ensure the database schema is stable between runs and
that no `.sql` file content has changed (including whitespace).

---

## Debugging tips

### Enable verbose logging

pysquirrel uses Python's standard `logging` module. To see debug output, set
the log level before running:

```bash
# Show all pysquirrel log messages (INFO and above)
PYTHONPATH=src python -c "
import logging; logging.basicConfig(level=logging.DEBUG)
from pysquirrel.cli import main; main()
" generate --database-url postgresql://user:pass@localhost/mydb
```

Or configure logging via environment variable:

```bash
# With Python 3.11+ you can use the -X log option
python -X log=DEBUG -m pysquirrel generate
```

Loggers used by pysquirrel:

| Logger | Purpose |
|---|---|
| `pysquirrel.codegen.format` | `ruff format` invocation and fallback |
| `pysquirrel.introspect.connection` | Connection pool lifecycle, server version checks |
| `pysquirrel.introspect.prepare` | Statement preparation, parameter introspection |

### Test the connection independently

If you suspect a connection issue, test the same DSN with `psql`:

```bash
psql "postgresql://user:pass@localhost:5432/mydb" -c "SELECT version();"
```

If `psql` cannot connect, pysquirrel will not be able to either.

### Verify SQL syntax

If a query fails during introspection, test it directly in `psql`:

```bash
psql "$DATABASE_URL" -c "PREPARE test AS <your_query_body>"
```

Common issues caught at this stage:

- Referencing tables or columns that don't exist
- Syntax errors in the SQL body
- Using features not supported by the connected Postgres version

### Inspect the generated file

The generated file is plain Python. Open it in your editor or run:

```bash
python -c "import sql_generated; print(sql_generated.__file__)"
```

If the file is missing entirely, `pysquirrel generate` may not have found any
`.sql` files — see [section 1](#1-no-sql-files-found).

### Check the hash header

The generated file includes a `# hash:` line with a SHA-256 digest of the
source `.sql` files. This is used by `pysquirrel check` to skip database
queries when nothing has changed:

```python
# AUTO-GENERATED by pysquirrel — do not edit manually.
# source: sql
# generated at: 2025-01-15 10:30:00 UTC
# hash: a1b2c3d4e5f6...
```

You can compare hashes manually to verify whether the source files have
changed since the last generation.

---

## FAQ

### Does pysquirrel support views?

Yes. Views are introspected the same way as tables. pysquirrel sees whatever
columns and types the view exposes through `PREPARE`/`EXPLAIN`.

### Does pysquirrel support functions or stored procedures?

pysquirrel can introspect `SELECT * FROM my_function()` like any other query.
However, `DO` blocks and `CALL` statements cannot be `EXPLAIN`ed, so
nullability inference falls back to "everything nullable" for those.

### What happens if I edit the generated file by hand?

Your changes will be overwritten the next time `pysquirrel generate` runs. The
file header warns: `AUTO-GENERATED by pysquirrel — do not edit manually.` Use
`pysquirrel check` in CI to catch accidental edits.

### Can I use pysquirrel with Django, SQLAlchemy, or another ORM?

pysquirrel generates standalone `asyncpg`-based code. It does not integrate
with ORM query sets or model definitions. You can use both in the same project
— just don't mix them on the same connection.

### What Python version is required?

pysquirrel generates code targeting Python 3.10+ (uses `X | Y` union syntax
and `list[T]` generic syntax without `from __future__ import annotations`).

### What Postgres version is required?

PostgreSQL 16 or later. pysquirrel uses `EXPLAIN (FORMAT JSON, VERBOSE,
GENERIC_PLAN)`, which requires the `GENERIC_PLAN` option introduced in
Postgres 16.

### Can I run pysquirrel without a database?

No. pysquirrel connects to a live Postgres instance to introspect query types
and nullability. However, the hash short-circuit in `pysquirrel check` means
that when `.sql` files have not changed, no database query is needed — making
CI fast for the common case.
