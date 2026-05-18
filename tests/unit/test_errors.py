"""Unit tests for pysquirrel.errors — error hierarchy."""

from __future__ import annotations

from pathlib import Path

from pysquirrel.errors import (
    ConfigError,
    IntrospectionError,
    PysquirrelError,
    QueryParseError,
    UnknownAnnotationError,
    UnsupportedTypeError,
)


class TestErrorHierarchy:
    def test_all_inherit_from_base(self) -> None:
        errors = [
            QueryParseError(Path("a.sql"), 1, "bad"),
            UnsupportedTypeError(Path("a.sql"), 23, "int8"),
            IntrospectionError(Path("a.sql"), "oops"),
            UnknownAnnotationError(Path("a.sql"), 5, "@foo"),
            ConfigError("no db"),
        ]
        for err in errors:
            assert isinstance(err, PysquirrelError)

    def test_query_parse_error_format(self) -> None:
        err = QueryParseError(Path("queries/a.sql"), 12, "unexpected token")
        assert str(err) == "queries/a.sql:12: unexpected token"
        assert err.file == Path("queries/a.sql")
        assert err.line == 12
        assert err.message == "unexpected token"

    def test_unsupported_type_error_format(self) -> None:
        err = UnsupportedTypeError(Path("b.sql"), 1234, "money")
        assert "money" in str(err)
        assert "1234" in str(err)
        assert err.oid == 1234

    def test_introspection_error_format(self) -> None:
        err = IntrospectionError(Path("c.sql"), "relation not found")
        assert "introspection failed" in str(err)
        assert "relation not found" in str(err)

    def test_unknown_annotation_error_format(self) -> None:
        err = UnknownAnnotationError(Path("d.sql"), 3, "@unknown")
        assert "d.sql:3" in str(err)
        assert "@unknown" in str(err)

    def test_config_error_format(self) -> None:
        err = ConfigError("bad url")
        assert str(err) == "bad url"
