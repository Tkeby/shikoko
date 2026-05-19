# Changelog

All notable changes to shikoko will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.1] - 2026-05-19

### Fixed

- **Enum-typed query parameters no longer crash introspection.**
  `shikoko generate` previously failed with
  `InvalidTextRepresentationError: invalid input value for enum <name>: ""`
  whenever a query bound a parameter to a user-defined enum type
  (e.g. `where paid_with = $2::payment_method`). The EXPLAIN
  `GENERIC_PLAN` prepass dispatches dummy values for each parameter to
  satisfy asyncpg's extended-query Bind step; the fallback for unknown
  OIDs was the empty string, which Postgres rejects as an invalid
  enum label. The fallback is now `NULL`, which the wire protocol
  accepts for every parameter type because Bind skips the
  type-specific input decoder on null parameters. User-defined
  domains and composites benefit from the same change.
  ([`src/shikoko/introspect/plan.py`](src/shikoko/introspect/plan.py))

## [0.1.0] - 2026-05-19

### Added

- **Nullability inference (M4):** shikoko now automatically infers
  whether a `SELECT` result column is nullable using three signals in
  priority order:
  1. Explicit `!` / `?` override suffixes on column aliases.
  2. `EXPLAIN (FORMAT JSON, VERBOSE, GENERIC_PLAN)` plan-tree walk to
     detect columns made nullable by outer joins (`LEFT`, `RIGHT`,
     `FULL`, `SEMI`).
  3. Fallback to `pg_attribute.attnotnull` from the catalog.
- **Override markers:** append `!` to a column alias to force non-null,
  or `?` to force nullable. See `docs/annotations.md` for details.
- **`nullability` module** (`src/shikoko/introspect/nullability.py`):
  pure plan-tree walker, override stripping, and async inference
  orchestrator.
- **`plan` module** (`src/shikoko/introspect/plan.py`): EXPLAIN plan
  parser, `run_explain` I/O runner with `GENERIC_PLAN` support, and
  `column_origins` for mapping plan outputs back to catalog metadata.
- **`build_query_ir`** now integrates nullability inference end-to-end:
  EXPLAIN → plan parse → column origins → walk → catalog fallback →
  `Field.nullable` on each output field.
- Determinism tests verifying that `set[int]` internal state does not
  leak into rendered output, and that `render_module` is byte-stable
  across repeated calls (modulo timestamp).
