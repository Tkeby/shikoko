"""Unit tests for shikoko.parser — SQL file parsing logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from shikoko.errors import QueryParseError, UnknownAnnotationError
from shikoko.parser import parse_sql_file


def _write_sql(tmp_path: Path, name: str, content: str) -> Path:
    """Write *content* to a temp .sql file and return its path."""
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestSimpleQuery:
    def test_body(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "select 1")
        result = parse_sql_file(path)
        assert result.body == "select 1"

    def test_name_from_filename(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "simple_query.sql", "select 1")
        result = parse_sql_file(path)
        assert result.name == "simple_query"

    def test_no_annotations(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "select 1")
        result = parse_sql_file(path)
        assert result.annotations == {}

    def test_no_doc(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "select 1")
        result = parse_sql_file(path)
        assert result.doc == ""


class TestDocComments:
    def test_single_line_doc(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "-- Find users.\nselect 1")
        result = parse_sql_file(path)
        assert result.doc == "Find users."

    def test_multi_line_doc(self, tmp_path: Path) -> None:
        path = _write_sql(
            tmp_path, "q.sql", "-- Find users.\n-- Returns all.\nselect 1"
        )
        result = parse_sql_file(path)
        assert result.doc == "Find users.\nReturns all."


class TestAnnotations:
    def test_one_annotation(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "-- @one\nselect 1")
        result = parse_sql_file(path)
        assert result.annotations.get("return_kind") == "one"

    def test_exec_annotation(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "-- @exec\ninsert into t values(1)")
        result = parse_sql_file(path)
        assert result.annotations.get("return_kind") == "exec"

    def test_name_annotation(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "-- @name: find_user\nselect 1")
        result = parse_sql_file(path)
        assert result.name == "find_user"

    def test_name_with_spaces(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "-- @name:  my query  \nselect 1")
        result = parse_sql_file(path)
        assert result.name == "my query"

    def test_combined_annotations(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "-- @one\n-- @name: foo\nselect 1")
        result = parse_sql_file(path)
        assert result.name == "foo"
        assert result.annotations.get("return_kind") == "one"

    def test_default_name_from_filename(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "find_user.sql", "select 1")
        result = parse_sql_file(path)
        assert result.name == "find_user"


class TestErrors:
    def test_unknown_annotation_raises(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "-- @unknown\nselect 1")
        with pytest.raises(UnknownAnnotationError) as exc_info:
            parse_sql_file(path)
        assert exc_info.value.annotation == "unknown"

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "")
        with pytest.raises(QueryParseError, match="no SQL statement"):
            parse_sql_file(path)

    def test_comments_only_raises(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "-- just comments")
        with pytest.raises(QueryParseError, match="no SQL statement"):
            parse_sql_file(path)


class TestSourceMetadata:
    def test_source_file_set(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "select 1")
        result = parse_sql_file(path)
        assert result.source_file == path

    def test_source_line_points_to_body(self, tmp_path: Path) -> None:
        path = _write_sql(
            tmp_path, "q.sql", "-- comment line 1\n-- comment line 2\nselect 1"
        )
        result = parse_sql_file(path)
        # Body starts at 0-indexed line 2, so source_line (1-based) = 3
        assert result.source_line == 3

    def test_source_line_no_comments(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "select 1")
        result = parse_sql_file(path)
        # Body starts at 0-indexed line 0, so source_line (1-based) = 1
        assert result.source_line == 1


class TestBodyWhitespace:
    def test_body_strips_leading_trailing_blank_lines(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "\n\nselect 1\n\n")
        result = parse_sql_file(path)
        assert result.body == "select 1"

    def test_body_preserves_internal_newlines(self, tmp_path: Path) -> None:
        path = _write_sql(tmp_path, "q.sql", "select id,\n       name\nfrom users")
        result = parse_sql_file(path)
        assert "select id," in result.body
        assert "from users" in result.body
