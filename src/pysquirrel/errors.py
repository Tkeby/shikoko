"""Typed errors with source location."""

from __future__ import annotations

from pathlib import Path


class PysquirrelError(Exception):
    """Base for all user-facing errors raised by pysquirrel."""


class QueryParseError(PysquirrelError):
    """Raised when a ``.sql`` file cannot be parsed."""

    def __init__(self, file: Path, line: int, message: str) -> None:
        self.file = file
        self.line = line
        self.message = message
        super().__init__(f"{file}:{line}: {message}")


class UnsupportedTypeError(PysquirrelError):
    """Raised when a Postgres OID has no mapped Python type."""

    def __init__(self, file: Path, oid: int, pg_type_name: str) -> None:
        self.file = file
        self.oid = oid
        self.pg_type_name = pg_type_name
        super().__init__(f"{file}: unsupported type {pg_type_name} (oid {oid})")


class IntrospectionError(PysquirrelError):
    """Raised when Postgres returns an error during introspection."""

    def __init__(self, file: Path, message: str) -> None:
        self.file = file
        self.message = message
        super().__init__(f"{file}: introspection failed: {message}")


class UnknownAnnotationError(PysquirrelError):
    """Raised when a query annotation is not recognised."""

    def __init__(self, file: Path, line: int, annotation: str) -> None:
        self.file = file
        self.line = line
        self.annotation = annotation
        super().__init__(f"{file}:{line}: unknown annotation: {annotation}")


class ConfigError(PysquirrelError):
    """Raised when connection settings cannot be resolved."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
