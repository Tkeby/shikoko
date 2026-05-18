"""Find ``sql/`` directories and ``.sql`` files under a project root."""

from __future__ import annotations

from pathlib import Path


def find_sql_directories(root: Path) -> list[Path]:
    """Return all directories literally named ``sql`` under *root*, sorted.

    Only exact directory names are matched — ``sql_backup/`` is ignored.
    """
    return sorted(p for p in root.rglob("sql") if p.is_dir())


def find_sql_files(root: Path) -> list[tuple[Path, Path]]:
    """Return ``(sql_dir, file_path)`` for every ``.sql`` file under *root*.

    *sql_dir* is the parent directory that is literally named ``sql``.
    Files that are not directly inside a ``sql/`` directory are excluded.
    Results are sorted by file path for deterministic ordering.
    """
    results: list[tuple[Path, Path]] = []
    for fpath in sorted(root.rglob("*.sql")):
        if fpath.is_file() and fpath.parent.name == "sql":
            results.append((fpath.parent, fpath))
    return results
