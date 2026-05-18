"""Unit tests for shikoko.types.oid_map — OID to Python type resolution."""

from __future__ import annotations

import pytest

from shikoko.codegen.ir import PyType
from shikoko.errors import UnsupportedTypeError
from shikoko.types.oid_map import resolve_type


class TestScalarTypes:
    def test_int4(self) -> None:
        result = resolve_type(23, "int4", "scalar")
        assert result == PyType("int", frozenset())

    def test_text(self) -> None:
        result = resolve_type(25, "text", "scalar")
        assert result == PyType("str", frozenset())

    def test_int8(self) -> None:
        result = resolve_type(20, "int8", "scalar")
        assert result == PyType("int", frozenset())

    def test_float8(self) -> None:
        result = resolve_type(701, "float8", "scalar")
        assert result == PyType("float", frozenset())

    def test_uuid(self) -> None:
        result = resolve_type(2950, "uuid", "scalar")
        assert result == PyType("UUID", frozenset({"from uuid import UUID"}))

    def test_bool(self) -> None:
        result = resolve_type(16, "bool", "scalar")
        assert result == PyType("bool", frozenset())

    def test_jsonb(self) -> None:
        result = resolve_type(3802, "jsonb", "scalar")
        assert result == PyType("Any", frozenset({"from typing import Any"}))


class TestArrayTypes:
    def test_int4_array(self) -> None:
        result = resolve_type(1007, "int4[]", "array")
        assert result == PyType("list[int]", frozenset())

    def test_text_array(self) -> None:
        result = resolve_type(1009, "text[]", "array")
        assert result == PyType("list[str]", frozenset())

    def test_uuid_array(self) -> None:
        result = resolve_type(2951, "uuid[]", "array")
        assert result == PyType("list[UUID]", frozenset({"from uuid import UUID"}))


class TestUnknownTypes:
    def test_unknown_scalar_oid_raises(self) -> None:
        with pytest.raises(UnsupportedTypeError) as exc_info:
            resolve_type(99999, "unknown_type", "scalar")
        assert exc_info.value.oid == 99999

    def test_unknown_array_oid_raises(self) -> None:
        with pytest.raises(UnsupportedTypeError):
            resolve_type(99999, "unknown_array", "array")
