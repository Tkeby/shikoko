# Usage

## Installation

pysquirrel requires Python 3.10+ and a running PostgreSQL 16+ instance.

```bash
pip install pysquirrel
```

This installs the `pysquirrel` CLI and its runtime dependencies (`asyncpg`, `pydantic`, `typer`). pysquirrel itself is only needed at generation time; your application at runtime only requires `asyncpg` and `pydantic`.

Optional: install `ruff` for automatic formatting of generated files:

```bash
pip install ruff
```

Verify the installation:

```bash
pysquirrel --version
```

---

## CLI reference

### Global options

| Option | Description |
|---|---|
| `--version` | Print the installed version and exit |
| `--help` | Show help text and exit |

### `pysquirrel generate`

Connect to Postgres, introspect every `.sql` file found under `sql/` directories, and write a `sql_generated.py` module next to each one.

```bash
pysquirrel generate [OPTIONS]
```

**Options:**

| Option | Default | Description |
|---|---|---|
| `--root DIR` | Current working directory | Project root to scan for `sql/` directories |
| `--database-url DSN` | *(see connection resolution)* | PostgreSQL connection string. Overrides `DATABASE_URL` env var. |

**What it does, step by step:**

1. Scans the project root for directories named `sql/`.
2. Finds all `.sql` files directly inside each `sql/` directory.
3. Connects to Postgres using the resolved connection settings.
4. For each `.sql` file:
   - Parse the leading comment block (docstring + annotations) and the SQL body.
   - Call `conn.prepare()` to extract parameter and column metadata.
   - Run `EXPLAIN (FORMAT JSON, VERBOSE, GENERIC_PLAN)` to infer nullability from outer joins.
   - Build an intermediate representation (IR) of the query.
5. Renders all queries in one Python module per `sql/` directory.
6. Formats the output via `ruff format` if `ruff` is on `PATH`.
7. Writes `sql_generated.py` next to each `sql/` directory.

**Example:**

```bash
pysquirrel generate --root ./my_project --database-url postgresql://user:pass@localhost:5432/mydb
```

### `pysquirrel check`

Regenerate in-memory and diff against the files already on disk. Designed for CI pipelines — exits `0` when everything is up to date, exits `1` with a unified diff on stderr when anything differs.

```bash
pysquirrel check [OPTIONS]
```

**Options:** identical to `generate` (`--root`, `--database-url`).

**What it does, step by step:**

1. For each `sql/` directory, compute a SHA-256 hash of its source `.sql` files.
2. If the existing `sql_generated.py` has a matching `# hash:` header line, skip that directory entirely (fast path — no database connection needed).
3. Otherwise, regenerate in-memory and produce a unified diff against the on-disk file.
4. Detect stale `sql_generated.py` files whose corresponding `sql/` directory no longer exists.
5. Detect missing `sql_generated.py` files where a `sql/` directory exists but no output has been generated yet.
6. Exit `0` if all generated files match, exit `1` otherwise with the diff printed to stderr.

**Example:**

```bash
pysquirrel check --root . --database-url "$DATABASE_URL"
```

---

## Connection configuration

pysquirrel resolves the Postgres connection using a four-level precedence chain:

1. **`--database-url` CLI flag** — highest priority. Accepts a full DSN:
   ```
   postgresql://user:password@host:port/dbname?connect_timeout=10
   ```

2. **`DATABASE_URL` environment variable** — used when `--database-url` is not provided.

3. **Individual environment variables** — resolved individually when neither of the above is set:
   - `PGHOST` (default: `localhost`)
   - `PGPORT` (default: `5432`)
   - `PGUSER` (default: `postgres`)
   - `PGPASSWORD` (default: empty string)
   - `PGDATABASE` (default: derived from project — see below)
   - `PGCONNECT_TIMEOUT` (default: `10`)

4. **Defaults** — `localhost:5432`, user `postgres`, no password. The database name falls back to:
   - The `[project].name` field in `pyproject.toml` (hyphens replaced with underscores), if present.
   - The name of the current working directory, if no `pyproject.toml` is found.

If no database name can be resolved, `pysquirrel generate` and `pysquirrel check` print an error and exit with code 1.

---

## Project layout

### Basic layout

A single `sql/` directory at the project root:

```
my_project/
├── sql/
│   ├── get_user.sql
│   ├── create_order.sql
│   └── list_items.sql
├── sql_generated.py        ← generated next to sql/
├── main.py                 ← your application code
└── pyproject.toml
```

### Multiple `sql/` directories

pysquirrel discovers every directory named `sql` under the project root. Each one gets its own `sql_generated.py`, written in the directory that contains the `sql/` folder.

```
my_project/
├── app/
│   ├── sql/
│   │   ├── find_user.sql
│   │   └── list_users.sql
│   ├── sql_generated.py    ← one per sql/ directory
│   └── main.py
├── admin/
│   ├── sql/
│   │   └── dashboard_stats.sql
│   └── sql_generated.py    ← independent module
└── pyproject.toml
```

Only `.sql` files directly inside a `sql/` directory are included. Nested subdirectories within `sql/` are ignored.

---

## SQL file format

Each `.sql` file represents exactly one query. The file has two sections:

1. **Leading comment block** — consecutive `--` lines at the top of the file. These provide the function name, docstring, and annotations.
2. **Query body** — everything after the comment block. This is the SQL that gets passed to `asyncpg`.

### Basic example

```sql
-- List all active users ordered by creation date.
select
  id,
  email,
  name,
  created_at
from users
where active = true
order by created_at desc
```

The filename stem (`list_active_users`) becomes the Python function name. The comment becomes the docstring.

### Annotations

Annotations are special `--` comments that pysquirrel recognizes:

#### `-- name: <query_name>` — override the function name

By default the function name equals the file's stem (e.g., `get_user.sql` → `get_user`). Use `-- name:` to override:

```sql
-- name: lookup_user_by_email
-- Find a user by their email address.
--
-- @one
select id, email, name
from users
where email = $1
```

Generates a function named `lookup_user_by_email` instead of `get_user`.

#### `-- @one` — return a single row or `None`

For queries that return at most one row. The generated function returns `RowModel | None` and uses `conn.fetchrow()` internally.

```sql
-- Fetch a user by primary key.
--
-- @one
select id, email, name, created_at
from users
where id = $1
```

#### `-- @exec` — execute without returning rows

For DML statements (`INSERT`, `UPDATE`, `DELETE`) that do not use `RETURNING`. The generated function returns `None` and uses `conn.execute()`.

```sql
-- Deactivate a user account.
--
-- @exec
update users set active = false where id = $1
```

#### No annotation — return a list (default)

When no return-kind annotation is present, the generated function returns `list[RowModel]` and uses `conn.fetch()`.

```sql
-- List all users.
select id, email, name from users order by id
```

### Nullability overrides

pysquirrel infers whether each column is nullable from three sources, applied in priority order:

1. **Explicit `!` / `?` suffixes** on column aliases in the `SELECT` list.
2. **EXPLAIN plan walking** — detects columns made nullable by `LEFT JOIN`, `RIGHT JOIN`, or `FULL JOIN`.
3. **Catalog fallback** — `pg_attribute.attnotnull` from the database schema.

When the inferred nullability is wrong, use a suffix on the column alias:

**`!` — force non-null:**

```sql
select
  o.id,
  u.email!   -- we know every order has a user
from orders o
left join users u on u.id = o.user_id
```

The `!` is stripped from the Python field name. The generated field is `email: str` instead of `email: str | None = None`.

**`?` — force nullable:**

```sql
select
  id,
  display_name,
  avatar_url?   -- might be null despite catalog
from users
```

The `?` is stripped from the Python field name. The generated field is `avatar_url: str | None = None`.

### Parameters

Use positional parameters (`$1`, `$2`, `$3`, ...) in your SQL. pysquirrel maps them to Python function parameters named `_1`, `_2`, `_3`, etc. All parameters are typed based on what Postgres reports and default to `None`, matching asyncpg's convention.

```sql
-- Create a new user and return the row.
--
-- @one
insert into users (email, name, org_id)
values ($1, $2, $3)
returning id, email, name, org_id, created_at
```

Generates:

```python
async def create_user(
    conn: asyncpg.Connection,
    _1: str | None = None,
    _2: str | None = None,
    _3: int | None = None,
) -> CreateUserRow | None:
    _row = await conn.fetchrow(_CREATE_USER_SQL, _1, _2, _3)
    if _row is None:
        return None
    return CreateUserRow.model_validate(dict(_row))
```

### Postgres enums

When a query references a Postgres enum type, pysquirrel generates a `StrEnum` class in the output module. The enum class is shared across all queries in the same `sql/` directory that reference it.

---

## Generated code structure

The generated `sql_generated.py` module has the following sections, always in this order for stable output:

### Header comment

```python
# AUTO-GENERATED by pysquirrel — do not edit manually.
# source: sql
# generated at: 2025-01-15 10:30:00 UTC
# hash: a1b2c3d4e5f6...
```

The `# hash:` line contains a SHA-256 digest of the source `.sql` files. The `check` subcommand uses this for a fast-path skip when nothing has changed.

### Imports

Only the imports needed by the types actually used in the queries:

```python
import asyncpg
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from enum import StrEnum
from uuid import UUID
from decimal import Decimal
```

### Enum classes

One `StrEnum` class per distinct Postgres enum type referenced by any query in the directory:

```python
class UserStatus(StrEnum):
    active = "active"
    inactive = "inactive"
    suspended = "suspended"
```

### Row model classes

One Pydantic `BaseModel` per query (except `-- @exec` queries). Models are frozen and strict:

```python
class ListUsersRow(BaseModel):
    """List all users ordered by creation date."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    email: str
    name: str | None = None
    created_at: datetime
```

Key properties:

- **Frozen** — instances are immutable after creation.
- **Strict** (`extra="forbid"`) — columns not present in the model definition will raise a `ValidationError` at runtime, catching schema drift early.
- **Nullable fields** default to `None` using `field: Type | None = None`.

### Async query functions

One async function per `.sql` file. Each takes `conn: asyncpg.Connection` as the first argument, followed by the typed parameters.

```python
_LIST_USERS_SQL = """
select id, email, name, created_at
from users
order by created_at desc
"""

async def list_users(conn: asyncpg.Connection) -> list[ListUsersRow]:
    """List all users ordered by creation date."""
    _rows = await conn.fetch(_LIST_USERS_SQL)
    return [ListUsersRow.model_validate(dict(_r)) for _r in _rows]
```

The SQL is stored as a module-level private constant (uppercase, prefixed with `_`). The function delegates to asyncpg's `conn.fetch()`, `conn.fetchrow()`, or `conn.execute()` depending on the return kind, then validates the result through Pydantic.

### Complete example

Given `sql/find_user_by_email.sql`:

```sql
-- Look up a user by email.
-- Returns None if not found.
--
-- @one
select
  id,
  email,
  name,
  created_at!
from users
where email = $1
```

pysquirrel generates:

```python
# AUTO-GENERATED by pysquirrel — do not edit manually.
# source: sql
# generated at: 2025-01-15 10:30:00 UTC
# hash: abc123...

import asyncpg
from datetime import datetime
from pydantic import BaseModel, ConfigDict

_FIND_USER_BY_EMAIL_SQL = """
select
  id, email, name, created_at
from users
where email = $1
"""


class FindUserByEmailRow(BaseModel):
    """Look up a user by email."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    email: str
    name: str | None = None
    created_at: datetime


async def find_user_by_email(
    conn: asyncpg.Connection,
    _1: str | None = None,
) -> FindUserByEmailRow | None:
    """Look up a user by email."""
    _row = await conn.fetchrow(_FIND_USER_BY_EMAIL_SQL, _1)
    if _row is None:
        return None
    return FindUserByEmailRow.model_validate(dict(_row))
```

---

## Using generated code in applications

### With asyncpg directly

```python
import asyncio
import asyncpg
from sql_generated import list_users, find_user_by_email, create_user

async def main() -> None:
    conn = await asyncpg.connect("postgresql://localhost/mydb")

    # List all users
    users = await list_users(conn)
    for u in users:
        print(u.email, u.name)

    # Find one user
    user = await find_user_by_email(conn, "alice@example.com")
    if user:
        print(f"Found: {user.name}")

    # Create a user (with RETURNING)
    new_user = await create_user(conn, "bob@example.com", "Bob", 1)
    if new_user:
        print(f"Created user {new_user.id}")

    await conn.close()

asyncio.run(main())
```

### With a connection pool

```python
import asyncpg
from sql_generated import list_users, ListUsersRow

async def get_all_users(pool: asyncpg.Pool) -> list[ListUsersRow]:
    async with pool.acquire() as conn:
        return await list_users(conn)
```

### With FastAPI

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
import asyncpg
from sql_generated import list_users, find_user_by_email, ListUsersRow, FindUserByEmailRow

pool: asyncpg.Pool | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool("postgresql://localhost/mydb")
    yield
    await pool.close()

app = FastAPI(lifespan=lifespan)

@app.get("/users", response_model=list[ListUsersRow])
async def get_users() -> list[ListUsersRow]:
    async with pool.acquire() as conn:
        return await list_users(conn)

@app.get("/users/{email}", response_model=FindUserByEmailRow | None)
async def get_user(email: str) -> FindUserByEmailRow | None:
    async with pool.acquire() as conn:
        return await find_user_by_email(conn, email)
```

### Importing from subdirectories

When you have multiple `sql/` directories, each one produces an independent `sql_generated.py`. Import using the module path relative to your project:

```python
from app.sql_generated import list_users
from admin.sql_generated import dashboard_stats
```

---

## CI integration

### GitHub Actions

Use `pysquirrel check` in your CI pipeline to ensure generated files are never out of date:

```yaml
name: Check generated SQL

on: [push, pull_request]

jobs:
  check:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: testdb
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install pysquirrel
        run: pip install pysquirrel

      - name: Check generated files
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/testdb
        run: pysquirrel check
```

### Shell script

```bash
#!/bin/bash
set -euo pipefail

pysquirrel check --root . --database-url "$DATABASE_URL"
```

### How the check fast path works

The generated file contains a `# hash:` line with the SHA-256 digest of the source `.sql` files. On `check`, pysquirrel:

1. Reads the existing `sql_generated.py` and extracts the stored hash.
2. Computes the current hash of the source `.sql` files.
3. If they match, skips the database round-trip entirely and reports up-to-date.

This makes CI fast when no SQL files have changed since the last generation.

---

## Environment variables reference

| Variable | Used by | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Connection resolution | *(none)* | Full PostgreSQL DSN. Overridden by `--database-url`. |
| `PGHOST` | Connection resolution | `localhost` | Postgres host. Only used when `DATABASE_URL` is not set. |
| `PGPORT` | Connection resolution | `5432` | Postgres port. Only used when `DATABASE_URL` is not set. |
| `PGUSER` | Connection resolution | `postgres` | Postgres user. Only used when `DATABASE_URL` is not set. |
| `PGPASSWORD` | Connection resolution | *(empty)* | Postgres password. Only used when `DATABASE_URL` is not set. |
| `PGDATABASE` | Connection resolution | *(see fallback)* | Database name. Falls back to `pyproject.toml` `[project].name` or the current directory name. |
| `PGCONNECT_TIMEOUT` | Connection resolution | `10` | Connection timeout in seconds. Only used when `DATABASE_URL` is not set. |

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. `generate` completed without errors, or `check` found all files up to date. |
| `1` | Failure. `generate` encountered an error (connection failure, parse error, unsupported type). `check` found differences between generated and on-disk files. |

When `check` exits with code `1`, a unified diff is printed to stdout showing what changed. Stale and missing files are reported on stderr.

---

## Error reference

All errors raised by pysquirrel are subclasses of `PysquirrelError`. They include file and line information where applicable.

| Error class | Cause |
|---|---|
| `QueryParseError` | A `.sql` file has no SQL body (only comments or empty). |
| `UnknownAnnotationError` | An unrecognized `-- @` annotation was found in the comment block. |
| `UnsupportedTypeError` | A Postgres column or parameter type (OID) is not in pysquirrel's type map. |
| `IntrospectionError` | Postgres returned an error during `PREPARE` or `EXPLAIN` (e.g., the query references a nonexistent table). |
| `ConfigError` | Connection settings could not be resolved (e.g., invalid DSN, no database name). |

Error messages include the source file path and line number when available:

```
sql/get_user.sql:3: unknown annotation: @batch
sql/create_order.sql: introspection failed: relation "orders" does not exist
Error: no database name resolved. Use --database-url, set DATABASE_URL, PGDATABASE, or run from a directory with a pyproject.toml.
```
