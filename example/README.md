# shikoko Demo — FastAPI App

A minimal FastAPI application that demonstrates shikoko's workflow:

1. Write SQL queries in `sql/*.sql` files.
2. Run `shikoko generate` to produce `sql_generated.py`.
3. Import and use the generated async functions in your app.
4. Run `shikoko check` in CI to verify generated files are up to date.

## Quick Start

### Prerequisites

- A running **PostgreSQL 16+** database (shikoko does not manage the server)
- [shikoko](https://pypi.org/project/shikoko/) installed (`pip install shikoko`)

### 1. Configure the database connection

Copy `.env.example` to `.env` and fill in your database URL:

```bash
cd app
cp .env.example .env
# Edit .env with your actual connection string:
#   DATABASE_URL=postgresql://user:password@localhost:5432/mydb
```

shikoko resolves the connection from the `DATABASE_URL` environment variable
(or individual `PGHOST` / `PGPORT` / `PGUSER` / `PGPASSWORD` / `PGDATABASE`
env vars). See the [connection resolution](#connection-resolution) section below.

### 2. Apply the schema

```bash
psql "$DATABASE_URL" -f app/migrations/001_init.sql
```

### 3. Generate the query module

```bash
shikoko generate --root example/app/
```

This reads `DATABASE_URL` from the environment, connects to your database,
and creates `example/app/sql_generated.py` containing:
- Pydantic row models (`ListUsersRow`, `FindUserByEmailRow`, etc.)
- Async query functions (`list_users`, `find_user_by_email`, etc.)

### 4. Install dependencies and run the app

```bash
cd example/app
pip install -e .
uvicorn main:app --reload
```

The app loads `DATABASE_URL` from `.env` via `python-dotenv` and uses
shikoko's `resolve_connection()` to configure the asyncpg pool.

Visit http://localhost:8000/docs for the interactive API docs.

### 5. Try the endpoints

```bash
# List all users
curl http://localhost:8000/users

# Find a user by email
curl http://localhost:8000/users/alice@example.com

# Create a new user
curl -X POST "http://localhost:8000/users?email=dave@example.com&name=Dave"

# List posts by user
curl http://localhost:8000/users/1/posts

# Health check
curl http://localhost:8000/health
```

## CI Gate: `shikoko check`

The `check` subcommand regenerates the Python module in-memory and diffs it
against the existing file. If they differ, it exits 1 with a unified diff —
perfect for CI:

```bash
shikoko check --root example/app/
```

If someone edits a `.sql` file but forgets to regenerate, CI catches it:

```bash
$ shikoko check --root example/app/
--- a/example/app/sql_generated.py
+++ b/example/app/sql_generated.py
@@ ... @@
- async def list_users(conn: asyncpg.Connection) -> list[ListUsersRow]:
+ async def list_users_with_posts(conn: asyncpg.Connection) -> list[ListUsersWithPostsRow]:
```

### Hash short-circuit

The generated file embeds a SHA-256 hash of the source `.sql` files in its
header. When `check` sees a matching hash, it skips the database round-trip
entirely — making CI fast when nothing has changed.

### CI example

See [`ci_demo.sh`](ci_demo.sh) for a complete CI workflow script. It assumes
`DATABASE_URL` is already set in the CI environment.

## Connection resolution

shikoko resolves the database connection using the following precedence:

1. `--database-url` CLI flag
2. `DATABASE_URL` environment variable
3. Individual `PGHOST` / `PGPORT` / `PGUSER` / `PGPASSWORD` / `PGDATABASE` environment variables
4. Defaults: `localhost:5432`, user `postgres`, database name from `pyproject.toml` or current directory name

## Project Structure

```
example/
├── app/
│   ├── main.py              # FastAPI app — imports sql_generated
│   ├── .env.example         # Template — copy to .env with your DATABASE_URL
│   ├── sql/
│   │   ├── list_users.sql
│   │   ├── find_user_by_email.sql
│   │   ├── create_user.sql
│   │   ├── delete_user.sql
│   │   └── list_posts_by_user.sql
│   ├── migrations/
│   │   └── 001_init.sql     # Schema + seed data
│   ├── sql_generated.py     # AUTO-GENERATED — do not edit
│   └── pyproject.toml
├── ci_demo.sh               # Example CI workflow
└── README.md
```
