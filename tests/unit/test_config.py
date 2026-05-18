"""Unit tests for pysquirrel.config — connection resolution logic."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pysquirrel.config import (
    ConnectionSettings,
    ProjectSettings,
    _parse_dsn,
    resolve_connection,
    resolve_project,
)
from pysquirrel.errors import ConfigError

# ---------------------------------------------------------------------------
# _parse_dsn
# ---------------------------------------------------------------------------


class TestParseDsn:
    def test_full_dsn(self) -> None:
        result = _parse_dsn(
            "postgresql://alice:secret@db.example.com:5433/mydb?connect_timeout=30"
        )
        assert result == ConnectionSettings(
            host="db.example.com",
            port=5433,
            user="alice",
            password="secret",
            database="mydb",
            timeout=30,
            original_dsn="postgresql://alice:secret@db.example.com:5433/mydb?connect_timeout=30",
        )

    def test_minimal_dsn(self) -> None:
        result = _parse_dsn("postgresql://localhost/testdb")
        assert result.host == "localhost"
        assert result.database == "testdb"

    def test_dsn_without_password(self) -> None:
        result = _parse_dsn("postgresql://postgres@localhost/myapp")
        assert result.user == "postgres"
        assert result.password == ""

    def test_invalid_scheme(self) -> None:
        with pytest.raises(ConfigError, match="must start with postgresql://"):
            _parse_dsn("mysql://localhost/mydb")

    def test_dsn_property(self) -> None:
        # When built from individual fields (no original_dsn), dsn is constructed
        settings = ConnectionSettings(
            host="h", port=5432, user="u", password="p", database="d", timeout=5
        )
        assert settings.dsn == "postgresql://u:p@h:5432/d?connect_timeout=5"

    def test_dsn_preserves_original(self) -> None:
        # When built from a DSN, the original is preserved verbatim
        original = "postgresql://igo:igo@localhost:54322/igo?sslmode=disable"
        settings = _parse_dsn(original)
        assert settings.dsn == original
        assert settings.database == "igo"
        assert settings.port == 54322


# ---------------------------------------------------------------------------
# resolve_connection — precedence chain
# ---------------------------------------------------------------------------


class TestResolveConnection:
    def test_explicit_database_url_wins(self) -> None:
        with patch.dict(
            os.environ, {"DATABASE_URL": "postgresql://localhost/envdb"}, clear=False
        ):
            result = resolve_connection(
                database_url="postgresql://localhost/explicitdb"
            )
        assert result.database == "explicitdb"

    def test_env_database_url(self) -> None:
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql://user:pass@remote:5433/remotedb"},
            clear=False,
        ):
            result = resolve_connection()
        assert result.host == "remote"
        assert result.port == 5433
        assert result.database == "remotedb"

    def test_pg_env_vars(self) -> None:
        env = {
            "PGHOST": "pgenvhost",
            "PGPORT": "5433",
            "PGUSER": "pgenvuser",
            "PGPASSWORD": "pgenvpass",
            "PGDATABASE": "pgenvdb",
            "PGCONNECT_TIMEOUT": "20",
        }
        with patch.dict(os.environ, env, clear=False):
            # Ensure DATABASE_URL is not set
            os.environ.pop("DATABASE_URL", None)
            result = resolve_connection()
        assert result.host == "pgenvhost"
        assert result.port == 5433
        assert result.user == "pgenvuser"
        assert result.password == "pgenvpass"
        assert result.database == "pgenvdb"
        assert result.timeout == 20

    def test_defaults(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = resolve_connection(root=tmp_path)
        assert result.host == "localhost"
        assert result.port == 5432
        assert result.user == "postgres"
        assert result.password == ""

    def test_database_fallback_from_pyproject(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "my-cool-app"\n')
        with patch.dict(os.environ, {}, clear=True):
            result = resolve_connection(root=tmp_path)
        assert result.database == "my_cool_app"


# ---------------------------------------------------------------------------
# resolve_project
# ---------------------------------------------------------------------------


class TestResolveProject:
    def test_root_defaults_to_cwd(self) -> None:
        project = resolve_project()
        assert project.root == Path.cwd().resolve()

    def test_explicit_root(self, tmp_path: Path) -> None:
        project = resolve_project(root=tmp_path)
        assert project.root == tmp_path.resolve()

    def test_database_url_forwarded(self, tmp_path: Path) -> None:
        project = resolve_project(
            root=tmp_path, database_url="postgresql://user:pass@localhost/mydb"
        )
        assert project.connection.database == "mydb"

    def test_project_settings_fields(self, tmp_path: Path) -> None:
        project = resolve_project(root=tmp_path)
        assert isinstance(project, ProjectSettings)
        assert isinstance(project.connection, ConnectionSettings)
        assert project.root == tmp_path.resolve()
