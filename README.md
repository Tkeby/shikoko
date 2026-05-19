# shikoko

**Type-safe Python code generator for PostgreSQL queries.**

[![CI](https://github.com/tsegaw/shikoko/actions/workflows/ci.yml/badge.svg)](https://github.com/tsegaw/shikoko/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/shikoko.svg)](https://pypi.org/project/shikoko/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Write SQL. Get typed Python. No ORM.

*shikoko* (ሽኮኮ) is Amharic for "squirrel". It reads `.sql` files, connects to a live Postgres database, introspects your queries via `PREPARE`/`EXPLAIN`, and generates a Python module with **Pydantic v2 row models**, **async functions**, and **enum classes** — so your database layer is fully typed, validated, and IDE-friendly without writing a single model class by hand.

## What is shikoko?

shikoko is a build-time code generator for Python projects that use [asyncpg](https://github.com/MagicStack/asyncpg) to talk to PostgreSQL. You write plain SQL files; shikoko connects to your database, introspects each query's parameter and result types, and emits a Python module with:

- **Pydantic v2 row models** (frozen, `extra='forbid'`) — one per query
- **Async functions** that accept `asyncpg.Connection` + typed parameters and return typed results
- **Enum classes** (`StrEnum`) for Postgres enum types
- **Automatic nullability inference** from `LEFT JOIN` / `RIGHT JOIN` / `FULL JOIN` via `EXPLAIN` plan walking, with manual `!`/`?` overrides

There is no runtime dependency beyond `asyncpg` and `pydantic`. shikoko itself is only needed at generation time.

## Quick start

### Install

```bash
pip install shikoko
```

### Set up your project

```
my_project/
├── sql/
│   ├── list_users.sql
│   ├── find_user_by_email.sql
│   └── create_user.sql
├── sql_generated.py   ← AUTO-GENERATED, never edit
├── main.py
└── pyproject.toml
```

### Write SQL

`sql/list_users.sql`:

```sql
-- List all users with org name.
select
  u.id,
  u.email,
  u.name,
  o.name as org_name
from users u
left join orgs o on o.id = u.org_id
order by u.id
```

### Generate

```bash
shikoko generate --database-url postgresql://user:pass@localhost:5432/mydb
```

### Use

```python
import asyncio
import asyncpg
from sql_generated import list_users

async def main():
    conn = await asyncpg.connect("postgresql://user:pass@localhost:5432/mydb")
    rows = await list_users(conn)
    for row in rows:
        print(row.email, row.org_name)
    await conn.close()

asyncio.run(main())
```

That's it. Your queries are typed, validated, and auto-completed in your IDE.

## SQL file format

Each `.sql` file in a `sql/` directory represents one query. Leading `--` comments become the generated function's docstring.

### File naming

The filename stem becomes the function name by default. To override it, add a `-- name:` annotation:

```sql
-- name: list_active_users
-- List only active users.
select id, email from users where active = true;
```

### Annotations

Annotations are special `--` comments that shikoko parses before the SQL body:

| Annotation | Behavior |
|---|---|
| `-- name: <query_name>` | Override the function name (default: file stem) |
| `-- @one` | Returns `RowModel \| None` (single row or `None`) |
| `-- @exec` | Returns `None` (for DML without `RETURNING`) |
| *(none)* | Returns `list[RowModel]` (default, zero or more rows) |

**`-- @one`** — for queries that return at most one row:

```sql
-- Find a single user by email.
--
-- @one
select id, email, name
from users
where email = $1
```

Generates:

```python
async def find_user_by_email(
    conn: asyncpg.Connection, _1: str | None = None
) -> FindUserByEmailRow | None:
    ...
```

**`-- @exec`** — for `INSERT`/`UPDATE`/`DELETE` without `RETURNING`:

```sql
-- Delete a user by id.
--
-- @exec
delete from users where id = $1
```

Generates:

```python
async def delete_user(
    conn: asyncpg.Connection, _1: int | None = None
) -> None:
    ...
```

### Nullability overrides

shikoko infers nullability automatically from three sources, in priority order:

1. **Explicit overrides** via `!` / `?` suffixes on column aliases
2. **EXPLAIN plan walking** detects columns made nullable by outer joins (`LEFT`, `RIGHT`, `FULL`)
3. **Catalog fallback** — `pg_attribute.attnotnull` from the database schema

When you need to override the inferred decision, append a marker to the column alias in your `SELECT` list:

**`!` — force non-null:**

```sql
select
  o.id,
  u.email!   -- we know every order has a user
from orders o
left join users u on u.id = o.user_id;
```

The `!` is stripped from the Python field name. The generated field will be `email: str` instead of `email: str | None = None`.

**`?` — force nullable:**

```sql
select
  id,
  display_name,
  avatar_url?   -- might be null despite catalog
from users;
```

The `?` is stripped from the Python field name. The generated field will be `avatar_url: str | None = None`.

### Parameters

Use positional parameters (`$1`, `$2`, ...) in your SQL. shikoko maps them to Python parameters named `_1`, `_2`, etc. All parameters are nullable with `= None` defaults, matching asyncpg's behavior.

```sql
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
    ...
```

## Generated code example

Given this SQL file at `sql/list_users.sql`:

```sql
-- List all users with org name.
-- Left join ensures users without an org are still included.
select
  u.id,
  u.email,
  u.name,
  o.name as org_name
from users u
left join orgs o on o.id = u.org_id
order by u.id
```

shikoko generates:

```python
# AUTO-GENERATED by shikoko — do not edit manually.
# source: sql
# generated at: 2025-01-15 10:30:00 UTC
# hash: a1b2c3d4e5f6...

import asyncpg
from pydantic import BaseModel, ConfigDict

_LIST_USERS_SQL = """
select
  u.id,
  u.email,
  u.name,
  o.name as org_name
from users u
left join orgs o on o.id = u.org_id
order by u.id
"""


class ListUsersRow(BaseModel):
    """List all users with org name."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    email: str
    name: str | None = None
    org_name: str | None = None


async def list_users(conn: asyncpg.Connection) -> list[ListUsersRow]:
    """List all users with org name."""
    _rows = await conn.fetch(_LIST_USERS_SQL)
    return [ListUsersRow.model_validate(dict(_r)) for _r in _rows]
```

Key details:

- The model is **frozen** (immutable) and **strict** (`extra='forbid'`) — extra columns from schema changes will raise a validation error, catching drift early.
- `name` and `org_name` are `str | None = None` because shikoko detected the `LEFT JOIN` via `EXPLAIN` plan walking and the catalog reports `name` as nullable.
- The SQL is stored as a module-level constant and passed to asyncpg directly.

## FastAPI integration example

The [`example/`](example/) directory contains a complete, runnable FastAPI application demonstrating the shikoko workflow.

### Steps

```bash
# 1. Install shikoko
pip install shikoko

# 2. Configure your database
#    Copy .env.example to .env and set DATABASE_URL to your running PostgreSQL 16+
cd example/app
cp .env.example .env
# Edit .env: DATABASE_URL=postgresql://user:password@localhost:5432/mydb

# 3. Apply the schema
psql "$DATABASE_URL" -f migrations/001_init.sql

# 4. Generate the query module
shikoko generate --root example/app/

# 5. Install app dependencies and run
pip install -e .
uvicorn main:app --reload
```

Visit http://localhost:8000/docs for the interactive API docs.

### Try the endpoints

```bash
curl http://localhost:8000/users
curl http://localhost:8000/users/alice@example.com
curl -X POST "http://localhost:8000/users?email=dave@example.com&name=Dave"
curl http://localhost:8000/users/1/posts
```

### App code

The FastAPI app imports the generated module directly and uses
`shikoko.config.resolve_connection()` to configure the asyncpg pool from
environment variables:

```python
from shikoko.config import resolve_connection
from sql_generated import (
    ListUsersRow,
    FindUserByEmailRow,
    create_user,
    delete_user,
    find_user_by_email,
    list_posts_by_user,
    list_users,
)

@app.get("/users", response_model=list[ListUsersRow])
async def get_users() -> list[ListUsersRow]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await list_users(conn)
```

`resolve_connection()` reads `DATABASE_URL` from the environment (or a `.env`
file via `python-dotenv`) and returns a `ConnectionSettings` with a `.dsn`
property ready for `asyncpg.create_pool()`.

See [`example/app/main.py`](example/app/main.py) for the full application.

## CLI reference

shikoko provides two subcommands via [Typer](https://typer.tiangolo.com/):

### `shikoko generate`

Connects to Postgres, introspects all `.sql` files, and writes `sql_generated.py`.

```bash
shikoko generate [OPTIONS]
```

| Option | Description |
|---|---|
| `--root DIR` | Project root directory. Defaults to current working directory. |
| `--database-url DSN` | PostgreSQL connection string. See connection resolution below. |

### `shikoko check`

Regenerates in-memory and diffs against the existing files on disk. Exits `0` if everything is up to date, exits `1` with a unified diff on mismatch. Designed for CI pipelines.

```bash
shikoko check [OPTIONS]
```

| Option | Description |
|---|---|
| `--root DIR` | Project root directory. Defaults to current working directory. |
| `--database-url DSN` | PostgreSQL connection string. See connection resolution below. |

**Hash short-circuit:** The generated file embeds a SHA-256 hash of the source `.sql` files. When `check` sees a matching hash, it skips the database round-trip entirely — making CI fast when nothing has changed.

### Connection resolution

shikoko resolves the database connection using the following precedence:

1. `--database-url` CLI flag
2. `DATABASE_URL` environment variable (also loaded from `.env` in the project root)
3. Individual `PGHOST` / `PGPORT` / `PGUSER` / `PGPASSWORD` / `PGDATABASE` environment variables
4. Defaults: `localhost:5432`, user `postgres`, database name from `pyproject.toml` or current directory name

The same resolution logic is available to your application code via the public
`shikoko.config.resolve_connection()` function. It returns a
`ConnectionSettings` with `.dsn`, `.host`, `.port`, `.user`, `.password`,
and `.database` attributes — ideal for configuring an asyncpg pool directly
from the same environment variables that `shikoko generate` / `shikoko check`
use.

```python
from shikoko.config import resolve_connection

settings = resolve_connection()
pool = await asyncpg.create_pool(dsn=settings.dsn)
```

### `shikoko --version`

Prints the installed version and exits.

## Type mapping

shikoko maps 40+ built-in Postgres types to Python types. The most common mappings:

| PostgreSQL | Python |
|---|---|
| `boolean` | `bool` |
| `smallint`, `integer`, `bigint`, `oid` | `int` |
| `real`, `double precision` | `float` |
| `numeric`, `decimal` | `Decimal` |
| `text`, `varchar`, `char`, `name`, `bpchar` | `str` |
| `date` | `date` |
| `time`, `timetz` | `time` |
| `timestamp`, `timestamptz` | `datetime` |
| `interval` | `timedelta` |
| `uuid` | `UUID` |
| `json`, `jsonb` | `Any` |
| `bytea` | `bytes` |
| `inet` | `IPv4Address \| IPv6Address` |
| `cidr` | `IPv4Network \| IPv6Network` |
| `macaddr`, `macaddr8` | `str` |
| `xml` | `str` |
| `bit`, `varbit` | `str` |
| `money` | `str` |
| `T[]` (any array) | `list[T]` |
| `enum_type` | `StrEnum` class |

Necessary imports (`datetime`, `Decimal`, `UUID`, etc.) are added automatically to the generated module.

See [`docs/type-mapping.md`](docs/type-mapping.md) for the complete table with OIDs and edge cases.

## Documentation

| Document | Description |
|---|---|
| [SQL annotations](docs/annotations.md) | `-- name:`, `-- @one`, `-- @exec`, nullability overrides (`!`/`?`) |
| [Type mapping](docs/type-mapping.md) | Full Postgres-to-Python type mapping table |
| [Usage guide](docs/usage.md) | Detailed usage documentation |
| [Example app](example/README.md) | Runnable FastAPI example with step-by-step instructions |
| [Changelog](CHANGELOG.md) | Release history |

## Requirements

- **Python 3.10+**
- **PostgreSQL 16+** (`EXPLAIN … GENERIC_PLAN` requires Postgres 16+)
- **asyncpg** >= 0.29
- **Pydantic** >= 2.6

## Reference

shikoko is a Python port of [Squirrel](https://github.com/giacomocavalieri/squirrel), an excellent Gleam library by Giacomo Cavalieri. Many of the core ideas — SQL-first code generation, `EXPLAIN`-driven nullability inference, and annotation syntax — originate from Squirrel.

## License
MIT license ([MIT](https://github.com/tsegaw/shikoko/blob/main/LICENSE))
