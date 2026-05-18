"""Unit tests for shikoko.discovery — SQL directory and file finding."""

from __future__ import annotations

from pathlib import Path

from shikoko.discovery import find_sql_directories, find_sql_files


def _touch(path: Path) -> Path:
    """Create an empty file (and parent dirs) and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


class TestFindSqlDirectories:
    def test_no_sql_dirs(self, tmp_path: Path) -> None:
        assert find_sql_directories(tmp_path) == []

    def test_finds_sql_dir(self, tmp_path: Path) -> None:
        _touch(tmp_path / "sql" / "a.sql")
        dirs = find_sql_directories(tmp_path)
        assert len(dirs) == 1
        assert dirs[0].name == "sql"

    def test_ignores_non_sql_dirs(self, tmp_path: Path) -> None:
        _touch(tmp_path / "sql_backup" / "a.sql")
        _touch(tmp_path / "mysqldir" / "b.sql")
        assert find_sql_directories(tmp_path) == []

    def test_nested_sql_dirs(self, tmp_path: Path) -> None:
        _touch(tmp_path / "app" / "sql" / "a.sql")
        _touch(tmp_path / "lib" / "sql" / "b.sql")
        dirs = find_sql_directories(tmp_path)
        assert len(dirs) == 2
        names = [d.parent.name for d in dirs]
        assert "app" in names
        assert "lib" in names

    def test_returns_path_dirs(self, tmp_path: Path) -> None:
        _touch(tmp_path / "sql" / "a.sql")
        dirs = find_sql_directories(tmp_path)
        assert all(isinstance(d, Path) for d in dirs)
        assert all(d.is_dir() for d in dirs)

    def test_results_are_sorted(self, tmp_path: Path) -> None:
        _touch(tmp_path / "z" / "sql" / "a.sql")
        _touch(tmp_path / "a" / "sql" / "b.sql")
        dirs = find_sql_directories(tmp_path)
        names = [d.parent.name for d in dirs]
        assert names == sorted(names)


class TestFindSqlFiles:
    def test_no_sql_files(self, tmp_path: Path) -> None:
        assert find_sql_files(tmp_path) == []

    def test_finds_sql_file(self, tmp_path: Path) -> None:
        _touch(tmp_path / "sql" / "a.sql")
        results = find_sql_files(tmp_path)
        assert len(results) == 1
        sql_dir, fpath = results[0]
        assert sql_dir.name == "sql"
        assert fpath.name == "a.sql"

    def test_only_sql_files(self, tmp_path: Path) -> None:
        _touch(tmp_path / "sql" / "a.sql")
        _touch(tmp_path / "sql" / "readme.txt")
        results = find_sql_files(tmp_path)
        assert len(results) == 1
        assert results[0][1].suffix == ".sql"

    def test_ignores_non_sql_parent(self, tmp_path: Path) -> None:
        _touch(tmp_path / "queries" / "a.sql")
        results = find_sql_files(tmp_path)
        assert results == []

    def test_subdirectory_not_matched(self, tmp_path: Path) -> None:
        """Files in sql/sub/ are NOT found — parent must be literally 'sql'."""
        _touch(tmp_path / "sql" / "sub" / "a.sql")
        results = find_sql_files(tmp_path)
        assert results == []

    def test_nested_sql_dirs(self, tmp_path: Path) -> None:
        _touch(tmp_path / "app" / "sql" / "a.sql")
        _touch(tmp_path / "lib" / "sql" / "b.sql")
        results = find_sql_files(tmp_path)
        assert len(results) == 2
        filenames = [r[1].name for r in results]
        assert "a.sql" in filenames
        assert "b.sql" in filenames

    def test_results_are_sorted(self, tmp_path: Path) -> None:
        _touch(tmp_path / "sql" / "z.sql")
        _touch(tmp_path / "sql" / "a.sql")
        results = find_sql_files(tmp_path)
        names = [r[1].name for r in results]
        assert names == sorted(names)

    def test_returns_tuples(self, tmp_path: Path) -> None:
        _touch(tmp_path / "sql" / "a.sql")
        results = find_sql_files(tmp_path)
        assert len(results) == 1
        sql_dir, fpath = results[0]
        assert isinstance(sql_dir, Path)
        assert isinstance(fpath, Path)
        assert fpath.parent == sql_dir
