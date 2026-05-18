"""`check` subcommand: regenerate to a buffer, diff against existing files."""

import difflib
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg

from pysquirrel.codegen.format import format_source
from pysquirrel.codegen.render import render_module
from pysquirrel.config import ConnectionSettings
from pysquirrel.discovery import find_sql_directories, find_sql_files
from pysquirrel.introspect.catalog import CatalogCache
from pysquirrel.introspect.prepare import TypeResolver, build_query_ir
from pysquirrel.parser import parse_sql_file


@dataclass
class CheckResult:
    """Outcome of a ``check`` run comparing generated output to disk.

    Attributes:
        matches: True when every generated file is byte-identical to the
            on-disk version and there are no missing or stale files.
        diffs: Mapping of output path → unified diff string for files that
            differ from the on-disk version.
        missing: Output paths that would be generated but have no
            corresponding ``sql_generated.py`` on disk.
        stale: On-disk ``sql_generated.py`` files whose parent ``sql/``
            directory no longer exists or contains no ``.sql`` files.
    """

    matches: bool
    diffs: dict[Path, str] = field(default_factory=dict)
    missing: list[Path] = field(default_factory=list)
    stale: list[Path] = field(default_factory=list)


def compute_source_hash(files: list[Path]) -> str:
    """Return a deterministic SHA-256 hex digest of *files*.

    Files are sorted by their resolved path. The hash covers the
    concatenation of each file's UTF-8 contents (with a path separator
    between them to prevent ambiguity).
    """
    hasher = hashlib.sha256()
    for fpath in sorted(files):
        hasher.update(fpath.resolve().as_posix().encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(fpath.read_bytes())
        hasher.update(b"\x00")
    return hasher.hexdigest()


def extract_hash_from_generated(source: str) -> str | None:
    """Extract the ``# hash:`` value from a generated file's header.

    Returns ``None`` when the header line is absent (e.g. files generated
    before the hash feature was introduced).
    """
    for line in source.splitlines():
        m = re.match(r"^#\s*hash:\s*(\S+)", line)
        if m:
            return m.group(1)
        # Stop scanning once past the header comment block.
        if line and not line.startswith("#"):
            break
    return None


async def check_pipeline(
    project_root: Path,
    conn_info: ConnectionSettings,
) -> CheckResult:
    """Run the generate pipeline in-memory and compare against existing files.

    For each ``sql/`` directory:
    1. Compute the source hash of its ``.sql`` files.
    2. If the existing ``sql_generated.py`` has a matching hash, skip.
    3. Otherwise, regenerate to a string buffer and diff.

    Returns a :class:`CheckResult` summarising all differences.
    """
    from pysquirrel.introspect.connection import connect_pool

    sql_files = find_sql_files(project_root)
    if not sql_files:
        return CheckResult(matches=True)

    # Group by sql/ directory.
    by_dir: dict[Path, list[Path]] = defaultdict(list)
    for sql_dir, fpath in sql_files:
        by_dir[sql_dir].append(fpath)

    diffs: dict[Path, str] = {}
    missing: list[Path] = []

    # Track which output paths we expect so we can detect stale files.
    expected_output_paths: set[Path] = set()
    for sql_dir in by_dir:
        expected_output_paths.add(sql_dir.parent / "sql_generated.py")

    # Detect stale generated files.
    all_sql_dirs = set(find_sql_directories(project_root))
    stale = _find_stale_files(project_root, all_sql_dirs, expected_output_paths)

    # Use the hash short-circuit for directories where the existing file
    # matches the current source hash, avoiding a DB round-trip.
    dirs_needing_introspection: list[tuple[Path, list[Path]]] = []
    for sql_dir, files in sorted(by_dir.items()):
        output_path = sql_dir.parent / "sql_generated.py"
        source_hash = compute_source_hash(files)

        if output_path.is_file():
            existing = output_path.read_text(encoding="utf-8")
            existing_hash = extract_hash_from_generated(existing)
            if existing_hash == source_hash:
                # Hash matches — this directory is up to date.
                continue

        # Either missing or hash mismatch — needs full introspection.
        dirs_needing_introspection.append((sql_dir, files))

    # Only connect to the database if there is work to do.
    if dirs_needing_introspection:
        from typing import cast

        async with connect_pool(conn_info) as pool, pool.acquire() as conn:
            typed_conn = cast(asyncpg.Connection, conn)
            catalog = CatalogCache(typed_conn)
            resolver = TypeResolver(catalog)

            for sql_dir, files in sorted(dirs_needing_introspection):
                output_path = sql_dir.parent / "sql_generated.py"
                source_hash = compute_source_hash(files)
                source_label = str(sql_dir.relative_to(project_root))

                queries_ir = []
                for fpath in sorted(files):
                    parsed = parse_sql_file(fpath)
                    ir = await build_query_ir(typed_conn, parsed, resolver)
                    queries_ir.append(ir)

                generated = render_module(
                    queries_ir, source_label, source_hash=source_hash
                )
                generated = await format_source(generated)

                if not output_path.is_file():
                    missing.append(output_path)
                    # Show the full file as a diff against /dev/null.
                    diff = _diff_strings("", generated, str(output_path))
                    diffs[output_path] = diff
                else:
                    existing = output_path.read_text(encoding="utf-8")
                    diff = _diff_strings(existing, generated, str(output_path))
                    if diff:
                        diffs[output_path] = diff

    all_matches = not diffs and not missing and not stale
    return CheckResult(matches=all_matches, diffs=diffs, missing=missing, stale=stale)


def _diff_strings(old: str, new: str, label: str) -> str:
    """Return a unified diff between *old* and *new*, or ``""`` if identical."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    result = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{label}",
        tofile=f"b/{label}",
    )
    return "".join(result)


def _find_stale_files(
    project_root: Path,
    active_sql_dirs: set[Path],
    expected_output_paths: set[Path],
) -> list[Path]:
    """Find ``sql_generated.py`` files that have no corresponding ``sql/`` dir."""
    stale: list[Path] = []
    for candidate in sorted(project_root.rglob("sql_generated.py")):
        if candidate.is_file() and candidate not in expected_output_paths:
            stale.append(candidate)
    return stale
