# codegen/ir.py
from dataclasses import dataclass
from enum import Enum


class ReturnKind(Enum):
    MANY = "many"  # default: list[RowModel]
    ONE = "one"  # -- @one: RowModel | None
    EXEC = "exec"  # -- @exec: None, used for INSERT/UPDATE/DELETE w/o RETURNING


@dataclass(frozen=True)
class PyType:
    # Rendered as a Python type annotation string in the final file.
    # e.g. "str", "int", "UUID", "list[int]", "MyEnum"
    annotation: str
    # Modules needed for this type, e.g. {"from uuid import UUID"}.
    imports: frozenset[str]


@dataclass(frozen=True)
class Param:
    name: str  # from arg position; user can rename via annotation
    py_type: PyType
    nullable: bool  # if true, default to None and accept Optional


@dataclass(frozen=True)
class Field:
    name: str  # snake_case, !/? stripped
    py_type: PyType
    nullable: bool


@dataclass(frozen=True)
class EnumIR:
    py_name: str  # PascalCase
    pg_name: str  # original
    variants: tuple[tuple[str, str], ...]  # (py_member, pg_label)


@dataclass(frozen=True)
class QueryIR:
    name: str  # function name
    doc: str  # from leading -- comments
    sql: str  # body, leading comments stripped
    params: tuple[Param, ...]
    row_model_name: str  # e.g. FindUserRow, or "" if EXEC
    fields: tuple[Field, ...]  # empty if EXEC
    return_kind: ReturnKind
    enums_used: tuple[EnumIR, ...]
    source_file: str  # for error messages and regen header
    source_line: int
