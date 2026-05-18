# Contributing to shikoko

Thank you for your interest in contributing. shikoko is a type-safe Python
code generator for PostgreSQL queries, and every contribution — bug reports,
documentation fixes, feature ideas, or pull requests — helps make it better.

This document covers everything you need to set up a development environment,
understand the codebase, and submit changes that align with the project's
conventions.

## Prerequisites

- **Python 3.10+**
- **PostgreSQL 16+** (for integration tests; `GENERIC_PLAN` requires it)
- **Docker** and **Docker Compose** (for running the test Postgres instance)
- **Git**

## Development setup

```bash
# 1. Clone the repository
git clone https://github.com/tsegaw/shikoko.git
cd shikoko

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Install the package with dev dependencies
pip install -e ".[dev]"

# 4. Verify the CLI works
shikoko --version

# 5. Run the unit tests (no Docker needed)
pytest tests/unit -q
```

If the unit tests pass, your environment is ready.

## Project structure

```
src/shikoko/
├── cli.py              # Typer CLI (generate, check)
├── config.py           # Connection string resolution
├── discovery.py        # Find sql/ dirs and .sql files
├── parser.py           # Parse .sql files → ParsedQuery
├── check.py            # check subcommand logic
├── errors.py           # Typed error classes
├── codegen/
│   ├── ir.py           # Intermediate representation dataclasses
│   ├── render.py       # IR → Python source string
│   ├── format.py       # ruff format integration
│   └── naming.py       # snake_case / PascalCase conversion
├── introspect/
│   ├── connection.py   # asyncpg pool helper
│   ├── catalog.py      # pg_type / pg_enum / pg_attribute cache
│   ├── prepare.py      # PREPARE + build QueryIR
│   ├── plan.py         # EXPLAIN plan parsing
│   └── nullability.py  # Nullability inference
└── types/
    ├── oid_map.py      # OID → Python type mapping
    ├── enums.py        # Enum discovery + naming
    └── types.py        # ColumnInfo, ParamInfo shared types

tests/
├── conftest.py         # Shared fixtures (pool, conn, skip_no_db)
├── unit/               # Pure Python, no Docker needed
├── integration/        # Requires Postgres on localhost:54323
├── fixtures/           # SQL schemas and query fixtures
└── snapshot/           # Syrupy snapshots for generated code

example/                # Demo FastAPI app with docker-compose
docs/                   # Documentation
```

### The generation pipeline

All code generation follows a single pipeline:

```
discover → parse → prepare (PREPARE + EXPLAIN) → nullability inference → render → format → write
```

Each stage maps to a source module:

| Stage | Module | Input | Output |
|---|---|---|---|
| Discover | `discovery.py` | Project root | `list[Path]` of `.sql` files |
| Parse | `parser.py` | `.sql` file | `ParsedQuery` |
| Prepare | `introspect/prepare.py` | `ParsedQuery` + live DB | `QueryIR` |
| Nullability | `introspect/nullability.py` | `EXPLAIN` plan | nullable flags on fields |
| Render | `codegen/render.py` | `QueryIR` | Python source string |
| Format | `codegen/format.py` | Source string | Formatted source string |
| Write / Diff | `check.py` / `cli.py` | Formatted source | File on disk or unified diff |

The core data structures that flow through this pipeline are defined in
`codegen/ir.py` (`QueryIR`, `Field`, `Param`, `PyType`, `EnumIR`) and
`parser.py` (`ParsedQuery`). Understanding these two files is the fastest way
to get oriented.

## Running tests

### Unit tests

Unit tests are pure Python and require no external services. They run in a few
seconds:

```bash
pytest tests/unit -q
```

Run these after every code change. All new logic that does not touch the
database belongs here.

### Integration tests

Integration tests require a running Postgres instance. The project ships a
Docker Compose configuration in `example/`:

```bash
# 1. Start the test database
docker compose -f example/docker-compose.yml up -d

# 2. Run integration tests
pytest tests/integration -q

# 3. Stop when done
docker compose -f example/docker-compose.yml down
```

The integration test database runs on `localhost:54323` with credentials
`shikoko:shikoko`. The `conftest.py` fixture uses `skip_no_db` to skip
integration tests cleanly when Postgres is unreachable, so the test suite never
fails just because Docker is not running.

### Test conventions

- `asyncio_mode = "auto"` is set in `pyproject.toml` — do not add
  `@pytest.mark.asyncio` decorators.
- Use the `pool` or `conn` fixtures from `tests/conftest.py` for database
  access; never call `asyncpg.connect` directly in tests.
- Snapshot tests use [syrupy](https://github.com/syrupy-project/syrupy) and
  live in `tests/snapshot/`.
- Integration fixtures apply and tear down schema in `tests/fixtures/schemas/`.

## Code style

### Formatting and linting

The project uses [ruff](https://docs.astral.sh/ruff/) for both formatting and
linting. Run both before committing:

```bash
ruff check . && ruff format .
```

Configuration lives in `pyproject.toml` under `[tool.ruff]`. The line length is
88 characters.

### Type checking

Type safety is a core goal of shikoko. Please run at least one type checker
before opening a PR:

```bash
mypy src/
# or
pyright src/
```

`mypy` is configured with `strict = true` in `pyproject.toml`. Every public
function should have full type annotations.

### General conventions

- **Use `logging`, not `print`.** Create a module-level logger:
  `logger = logging.getLogger(__name__)`.
- **Comments explain *why*, not *what*.** Avoid comments that narrate the code.
  If the code is unclear, rewrite it.
- **SQL in Python uses lowercase** with `$1, $2` placeholders. Never interpolate
  user input into SQL.
- **All I/O is `async`.** Use `asyncpg` directly; never an ORM or synchronous
  database driver.
- **Imports are grouped:** standard library, then third-party, then
  first-party, separated by blank lines. No wildcard imports.

## How to add a new Postgres type mapping

Type mappings live in `src/shikoko/types/oid_map.py`. The file contains two
lookup tables:

- `BUILTIN_OIDS` — maps scalar type OIDs to `PyType` instances
- `_BUILTIN_ARRAY_OIDS` — maps array OIDs to their element OIDs

To add a new type:

1. Look up the OID in the
   [Postgres source](https://github.com/postgres/postgres/blob/master/src/include/catalog/pg_type.dat).
2. Add an entry to `BUILTIN_OIDS`:

```python
from shikoko.codegen.ir import PyType

_MY_IMPORT = frozenset({"from mymodule import MyType"})

BUILTIN_OIDS: dict[int, PyType] = {
    # ...existing entries...
    1234: PyType("MyType", _MY_IMPORT),
}
```

3. If the type has a corresponding array type, add it to
   `_BUILTIN_ARRAY_OIDS`:

```python
_BUILTIN_ARRAY_OIDS: dict[int, int] = {
    # ...existing entries...
    1235: 1234,  # MyType[]
}
```

4. Add a unit test in `tests/unit/test_oid_map.py` that verifies the new OID
   resolves correctly via `resolve_type()`.

5. If the type requires special handling during `PREPARE`, check
   `introspect/prepare.py`'s `TypeResolver` class as well.

## How to add a new annotation

Annotations are special `--` comments that shikoko parses from the leading
comment block of a `.sql` file. The current system supports:

- `-- name: <query_name>` — override the function name
- `-- @one` — return a single row or `None`
- `-- @exec` — return `None` (DML without `RETURNING`)

To add a new annotation:

1. **Define the behavior.** What does the annotation change? Is it a return
   kind, a naming hint, or something that affects code generation?

2. **Update `parser.py`:**
   - Add the annotation name to `_KNOWN_ANNOTATIONS` in
     `src/shikoko/parser.py`.
   - Add parsing logic in the `parse_sql_file` function if the annotation takes
     a value.

3. **Update `codegen/ir.py`:**
   - Add a new `ReturnKind` variant (if it affects return type) or a new field
     on `QueryIR` (if it carries data).

4. **Update `codegen/render.py`:**
   - Handle the new annotation in the rendering logic.

5. **Add tests:**
   - `tests/unit/test_parser.py` — parsing the annotation from SQL text
   - `tests/unit/test_render.py` — rendering the annotation into Python source
   - `tests/integration/` — end-to-end if it touches `PREPARE`/`EXPLAIN`

## Pull request process

1. **Fork** the repository and create a feature branch from `main`.
2. **Make your changes** with clear, focused commits.
3. **Add tests.** Unit tests for pure logic, integration tests for anything
   that touches the database. Every PR should include tests.
4. **Run the full check suite locally:**

   ```bash
   pytest tests/unit -q
   pytest tests/integration -q
   ruff check . && ruff format .
   mypy src/
   ```

5. **Write clear commit messages.** This project uses
   [Conventional Commits](https://www.conventionalcommits.org/) — for example:
   `feat: add tsvector type mapping`, `fix: handle empty SQL files`,
   `docs: clarify annotation syntax`.

6. **Open a pull request** against `main` with a description of what changed
   and why. Reference any related issues.

7. **Respond to review feedback.** All PRs require at least one review before
   merging.

## Reporting issues

If you find a bug or have a feature request, please open an issue on
[GitHub Issues](https://github.com/tsegaw/shikoko/issues) with:

- A clear title and description.
- Steps to reproduce (for bugs), including the `.sql` file content and the
  generated output.
- The Python version, shikoko version, and PostgreSQL version you are using.
- Any relevant error messages or stack traces.

When reporting a type mapping issue, include the Postgres type OID if possible
(you can find it with `SELECT oid, typname FROM pg_type WHERE typname =
'your_type'`).

## License

By contributing to shikoko, you agree that your contributions will be
licensed under the [MIT License](https://github.com/tsegaw/shikoko/blob/main/LICENSE).
