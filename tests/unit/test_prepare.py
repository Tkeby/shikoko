"""Unit tests for prepare-module override extraction and stripping.

Tests the pure regex-based functions that handle ``!``/``?`` override
suffixes on column aliases and qualified column references.
"""

from __future__ import annotations

from shikoko.introspect.prepare import (
    _extract_overrides,
    _strip_override_suffixes,
)


class TestExtractOverrides:
    def test_as_alias_bang(self) -> None:
        assert _extract_overrides("select x as name! from t") == ["!"]

    def test_as_alias_qmark(self) -> None:
        assert _extract_overrides("select x as name? from t") == ["?"]

    def test_no_override(self) -> None:
        assert _extract_overrides("select x as name from t") == [None]

    def test_mixed_overrides(self) -> None:
        sql = "select x as a!, y as b, z as c? from t"
        assert _extract_overrides(sql) == ["!", None, "?"]

    def test_qualified_column_bang(self) -> None:
        """Override on qualified column reference: ``u.col!``"""
        assert _extract_overrides("select u.id! from users u") == ["!"]

    def test_qualified_column_qmark(self) -> None:
        """Override on qualified column reference: ``u.col?``"""
        assert _extract_overrides("select u.id? from users u") == ["?"]

    def test_qualified_with_as_alias(self) -> None:
        """AS alias override takes precedence over qualified-column pattern."""
        sql = "select u.id as my_id! from users u"
        assert _extract_overrides(sql) == ["!"]

    def test_multiple_with_qualified(self) -> None:
        """Mix of AS overrides and qualified-column overrides."""
        sql = "select u.id!, o.name as org_name? from users u left join orgs o on o.id = u.org_id"
        assert _extract_overrides(sql) == ["!", "?"]

    def test_expression_no_override(self) -> None:
        """Computed expression with alias but no override."""
        sql = "select count(*) as total from users"
        assert _extract_overrides(sql) == [None]

    def test_expression_with_override(self) -> None:
        """Computed expression with alias override."""
        sql = "select count(*) as total! from users"
        assert _extract_overrides(sql) == ["!"]

    def test_qualified_column_no_alias(self) -> None:
        """No alias and no override on qualified column."""
        sql = "select u.id from users u"
        assert _extract_overrides(sql) == [None]


class TestStripOverrideSuffixes:
    def test_as_alias_bang(self) -> None:
        assert _strip_override_suffixes("select x as name! from t") == (
            "select x as name from t"
        )

    def test_as_alias_qmark(self) -> None:
        assert _strip_override_suffixes("select x as name? from t") == (
            "select x as name from t"
        )

    def test_qualified_column_bang(self) -> None:
        """Qualified column ``u.col!`` → ``u.col``."""
        assert _strip_override_suffixes("select u.id! from users u") == (
            "select u.id from users u"
        )

    def test_qualified_column_qmark(self) -> None:
        """Qualified column ``u.col?`` → ``u.col``."""
        assert _strip_override_suffixes("select u.id? from users u") == (
            "select u.id from users u"
        )

    def test_mixed_as_and_qualified(self) -> None:
        """Both patterns in the same SQL."""
        sql = "select u.id!, o.name as org_name? from users u left join orgs o on o.id = u.org_id"
        expected = "select u.id, o.name as org_name from users u left join orgs o on o.id = u.org_id"
        assert _strip_override_suffixes(sql) == expected

    def test_no_overrides_untouched(self) -> None:
        """SQL without overrides passes through unchanged."""
        sql = "select u.id, o.name as org_name from users u left join orgs o on o.id = u.org_id"
        assert _strip_override_suffixes(sql) == sql

    def test_expression_alias_override(self) -> None:
        """``count(*) as total!`` → ``count(*) as total``."""
        assert _strip_override_suffixes("select count(*) as total! from users") == (
            "select count(*) as total from users"
        )

    def test_not_equals_untouched(self) -> None:
        """``!=`` in WHERE should NOT be stripped."""
        sql = "select id from users where id != 0"
        assert _strip_override_suffixes(sql) == sql

    def test_coalesce_alias_override(self) -> None:
        """``coalesce(...) as name?`` → ``coalesce(...) as name``."""
        sql = "select coalesce(name, 'anon') as name? from users"
        assert _strip_override_suffixes(sql) == (
            "select coalesce(name, 'anon') as name from users"
        )
