"""Env var resolution, project discovery, connection settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from pysquirrel.errors import ConfigError

_DEFAULT_HOST = "localhost"
_DEFAULT_PORT = 5432
_DEFAULT_USER = "postgres"
_DEFAULT_PASSWORD = ""
_DEFAULT_TIMEOUT = 10


@dataclass(frozen=True)
class ConnectionSettings:
    """Resolved Postgres connection parameters."""

    host: str = _DEFAULT_HOST
    port: int = _DEFAULT_PORT
    user: str = _DEFAULT_USER
    password: str = _DEFAULT_PASSWORD
    database: str = ""
    timeout: int = _DEFAULT_TIMEOUT
    original_dsn: str | None = None

    @property
    def dsn(self) -> str:
        """Return the original DSN if available, otherwise build one."""
        if self.original_dsn is not None:
            return self.original_dsn
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
            f"?connect_timeout={self.timeout}"
        )


@dataclass(frozen=True)
class ProjectSettings:
    """Resolved project-level settings."""

    root: Path
    connection: ConnectionSettings = field(default_factory=ConnectionSettings)


def _project_name_from_pyproject(root: Path) -> str | None:
    """Read ``[project].name`` from *root*/``pyproject.toml`` if present."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None

    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found]
        except ImportError:
            return None

    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    name: str | None = data.get("project", {}).get("name")
    return name


def resolve_connection(
    *,
    database_url: str | None = None,
    root: Path | None = None,
) -> ConnectionSettings:
    """Resolve connection settings following the precedence chain.

    1. Explicit ``database_url`` (from ``--database-url`` flag).
    2. ``DATABASE_URL`` environment variable.
    3. Individual ``PGHOST`` / ``PGPORT`` / … env vars.
    4. Sensible defaults (localhost:5432, user ``postgres``, db from project
       name).
    """
    dsn = database_url or os.environ.get("DATABASE_URL")
    if dsn:
        return _parse_dsn(dsn)

    return ConnectionSettings(
        host=os.environ.get("PGHOST", _DEFAULT_HOST),
        port=int(os.environ.get("PGPORT", str(_DEFAULT_PORT))),
        user=os.environ.get("PGUSER", _DEFAULT_USER),
        password=os.environ.get("PGPASSWORD", _DEFAULT_PASSWORD),
        database=os.environ.get("PGDATABASE", _database_name_fallback(root)),
        timeout=int(os.environ.get("PGCONNECT_TIMEOUT", str(_DEFAULT_TIMEOUT))),
    )


def resolve_project(
    *,
    root: Path | None = None,
    database_url: str | None = None,
) -> ProjectSettings:
    """Resolve full project settings: root directory + connection."""
    project_root = (root or Path.cwd()).resolve()
    return ProjectSettings(
        root=project_root,
        connection=resolve_connection(database_url=database_url, root=project_root),
    )


def _database_name_fallback(root: Path | None) -> str:
    """Derive database name from the project directory or ``pyproject.toml``."""
    if root is not None:
        name = _project_name_from_pyproject(root)
        if name:
            return name.replace("-", "_")

    return Path.cwd().name


def _parse_dsn(dsn: str) -> ConnectionSettings:
    """Parse a ``postgresql://`` DSN into individual fields.

    Handles ``postgresql://user:pass@host:port/dbname?k=v`` form.
    """
    if not dsn.startswith("postgresql://"):
        raise ConfigError(
            f"Invalid DATABASE_URL: must start with postgresql://, got {dsn!r}"
        )

    try:
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(dsn)
        query = parse_qs(parsed.query)

        timeout_str = query.get("connect_timeout", [str(_DEFAULT_TIMEOUT)])[0]

        return ConnectionSettings(
            host=parsed.hostname or _DEFAULT_HOST,
            port=parsed.port or _DEFAULT_PORT,
            user=parsed.username or _DEFAULT_USER,
            password=parsed.password or _DEFAULT_PASSWORD,
            database=parsed.path.lstrip("/") or "",
            timeout=int(timeout_str),
            original_dsn=dsn,
        )
    except (ValueError, KeyError) as exc:
        raise ConfigError(f"Invalid DATABASE_URL: {exc}") from exc
