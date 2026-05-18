# shikoko Demo — FastAPI App

A minimal FastAPI application that demonstrates shikoko's workflow:

1. Write SQL queries in `sql/*.sql` files.
2. Run `shikoko generate` to produce `sql_generated.py`.
3. Import and use the generated async functions in your app.
4. Run `shikoko check` in CI to verify generated files are up to date.

## Quick Start

### 1. Start Postgres

```bash
# From the example/ directory:
docker compose -f docker-compose.yml up -d
# Wait for it to be healthy:
docker compose -f docker-compose.yml logs -f db
```

### 2. Apply the schema

```bash
psql postgresql://shikoko:shikoko@localhost:54323/shikoko \
  -f app/migrations/001_init.sql
```

### 3. Generate the query module

```bash
# From the project root (or install shikoko first: pip install -e .)
shikoko generate --root example/app/ \
  --database-url postgresql://shikoko:shikoko@localhost:54323/shikoko
```

This creates `example/app/sql_generated.py` containing:
- Pydantic row models (`ListUsersRow`, `FindUserByEmailRow`, etc.)
- Async query functions (`list_users`, `find_user_by_email`, etc.)

### 4. Run the app

```bash
cd example/app
pip install fastapi uvicorn asyncpg
DATABASE_URL=postgresql://shikoko:shikoko@localhost:54323/shikoko \
  uvicorn main:app --reload
```

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
# In CI:
shikoko check --root example/app/ \
  --database-url postgresql://shikoko:shikoko@localhost:54323/shikoko
```

If someone edits a `.sql` file but forgets to regenerate, CI catches it:

```bash
$ shikoko check --root example/app/ --database-url ...
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

## Project Structure

```
example/
├── app/
│   ├── main.py              # FastAPI app — imports sql_generated
│   ├── sql/
│   │   ├── list_users.sql
│   │   ├── find_user_by_email.sql
│   │   ├── create_user.sql
│   │   ├── delete_user.sql
│   │   └── list_posts_by_user.sql
│   ├── migrations/
│   │   └── 001_init.sql     # Schema + seed data
│   ├── sql_generated.py     # AUTO-GENERATED — do not edit
│   ├── Dockerfile
│   └── pyproject.toml
├── docker-compose.yml       # Postgres for tests
├── demo-compose.yml         # Postgres + app for full demo
├── ci_demo.sh               # Example CI workflow
└── docker/
    └── postgres/
        ├── Dockerfile
        └── postgresql.conf
```
