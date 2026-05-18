"""Unit tests for pysquirrel.codegen.naming — identifier conversion."""

from __future__ import annotations

from pathlib import Path

from pysquirrel.codegen.naming import (
    row_model_name,
    to_module_name,
    to_pascal_case,
    to_snake_case,
)


class TestToPascalCase:
    def test_simple(self) -> None:
        assert to_pascal_case("find_user") == "FindUser"

    def test_single_word(self) -> None:
        assert to_pascal_case("user") == "User"

    def test_empty(self) -> None:
        assert to_pascal_case("") == ""

    def test_three_parts(self) -> None:
        assert to_pascal_case("a_b_c") == "ABC"

    def test_trailing_underscore(self) -> None:
        assert to_pascal_case("hello_") == "Hello"

    def test_leading_underscore(self) -> None:
        assert to_pascal_case("_hello") == "Hello"

    def test_double_underscore(self) -> None:
        assert to_pascal_case("hello__world") == "HelloWorld"


class TestToSnakeCase:
    def test_pascal_case(self) -> None:
        assert to_snake_case("FindUser") == "find_user"

    def test_single_word(self) -> None:
        assert to_snake_case("user") == "user"

    def test_already_snake(self) -> None:
        assert to_snake_case("find_user") == "find_user"

    def test_uppercase_acronym(self) -> None:
        # "ABC" → the regex only inserts _ before uppercase after lowercase/digit
        # So "ABC" → "abc" (no lowercase char precedes any uppercase)
        assert to_snake_case("ABC") == "abc"

    def test_mixed_acronym(self) -> None:
        # "XMLParser": the regex (?<=[a-z0-9])([A-Z]) only inserts _ before
        # uppercase preceded by lowercase/digit. No lowercase before 'P',
        # so no underscore inserted. Result: "xmlparser".
        assert to_snake_case("XMLParser") == "xmlparser"


class TestToModuleName:
    def test_simple_sql_dir(self, tmp_path: Path) -> None:
        sql_dir = tmp_path / "app" / "sql"
        assert to_module_name(sql_dir, tmp_path) == "app.sql_generated"

    def test_root_sql_dir(self, tmp_path: Path) -> None:
        sql_dir = tmp_path / "sql"
        assert to_module_name(sql_dir, tmp_path) == "sql_generated"

    def test_deeply_nested(self, tmp_path: Path) -> None:
        sql_dir = tmp_path / "a" / "b" / "sql"
        assert to_module_name(sql_dir, tmp_path) == "a.b.sql_generated"


class TestRowModelName:
    def test_simple(self) -> None:
        assert row_model_name("find_user") == "FindUserRow"

    def test_two_words(self) -> None:
        assert row_model_name("list_all") == "ListAllRow"

    def test_single_word(self) -> None:
        assert row_model_name("count") == "CountRow"

    def test_three_words(self) -> None:
        assert row_model_name("get_user_by_id") == "GetUserByIdRow"
