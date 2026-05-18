"""snake_case / PascalCase conversion and identifier derivation."""

from __future__ import annotations

import re
from pathlib import Path


def to_pascal_case(snake: str) -> str:
    """Convert ``snake_case`` to ``PascalCase``."""
    return "".join(part.capitalize() for part in snake.split("_") if part)


def to_snake_case(s: str) -> str:
    """Convert ``PascalCase`` or ``camelCase`` to ``snake_case``."""
    # Insert underscore before each uppercase letter that follows a
    # lowercase letter or digit, then lowercase everything.
    result = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", s)
    return result.lower()


def to_module_name(sql_dir: Path, root: Path) -> str:
    """Derive a generated module name from the *sql_dir* path.

    For example, if *sql_dir* is ``app/sql`` relative to *root*,
    the result is ``app.sql_generated``.

    The ``sql`` directory name itself is replaced with ``sql_generated``.
    """
    try:
        rel = sql_dir.relative_to(root)
    except ValueError:
        rel = sql_dir

    parts = list(rel.parts)
    if parts and parts[-1] == "sql":
        parts[-1] = "sql_generated"
    else:
        parts.append("sql_generated")

    return ".".join(parts)


def row_model_name(query_name: str) -> str:
    """Derive the row-model class name from a query name.

    For example, ``find_user`` → ``FindUserRow``.
    """
    return f"{to_pascal_case(query_name)}Row"
