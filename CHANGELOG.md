# Changelog

All notable changes to shikoko will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
