"""Unit tests for pysquirrel.codegen.render — IR → Python source."""

from __future__ import annotations

from pysquirrel.codegen.ir import Field, Param, PyType, QueryIR, ReturnKind
from pysquirrel.codegen.render import render_module


def _make_query(
    name: str = "find_user",
    *,
    doc: str = "",
    sql: str = "select id, email from users where id = $1",
    params: tuple[Param, ...] = (),
    fields: tuple[Field, ...] = (),
    return_kind: ReturnKind = ReturnKind.MANY,
    row_model_name: str = "FindUserRow",
) -> QueryIR:
    """Helper to build a QueryIR with sensible defaults."""
    return QueryIR(
        name=name,
        doc=doc,
        sql=sql,
        params=params,
        row_model_name=row_model_name,
        fields=fields,
        return_kind=return_kind,
        enums_used=(),
        source_file="test.sql",
        source_line=1,
    )


_INT = PyType("int", frozenset())
_STR = PyType("str", frozenset())
_UUID = PyType("UUID", frozenset({"from uuid import UUID"}))


class TestRenderSimpleManyQuery:
    def test_no_future_annotations(self) -> None:
        # Generated modules deliberately do not use ``from __future__
        # import annotations``: PEP 604 union syntax works at runtime in
        # py3.10+, and omitting the future import lets Pydantic v2
        # resolve field annotations in dynamically-loaded modules.
        q = _make_query(return_kind=ReturnKind.MANY, fields=(Field("id", _INT, True),))
        source = render_module([q], "sql")
        assert "from __future__ import annotations" not in source

    def test_has_asyncpg_import(self) -> None:
        q = _make_query(return_kind=ReturnKind.MANY, fields=(Field("id", _INT, True),))
        source = render_module([q], "sql")
        assert "import asyncpg" in source

    def test_has_pydantic_import(self) -> None:
        q = _make_query(return_kind=ReturnKind.MANY, fields=(Field("id", _INT, True),))
        source = render_module([q], "sql")
        assert "from pydantic import BaseModel, ConfigDict" in source

    def test_has_sql_constant(self) -> None:
        q = _make_query(
            name="find_user",
            sql="select id from users",
            return_kind=ReturnKind.MANY,
            fields=(Field("id", _INT, True),),
        )
        source = render_module([q], "sql")
        assert '_FIND_USER_SQL = """' in source
        assert "select id from users" in source

    def test_has_row_model_class(self) -> None:
        q = _make_query(
            return_kind=ReturnKind.MANY,
            fields=(Field("id", _INT, True), Field("name", _STR, True)),
        )
        source = render_module([q], "sql")
        assert "class FindUserRow(BaseModel):" in source

    def test_row_model_has_config(self) -> None:
        q = _make_query(
            return_kind=ReturnKind.MANY,
            fields=(Field("id", _INT, True),),
        )
        source = render_module([q], "sql")
        assert "model_config = ConfigDict(frozen=True, extra='forbid')" in source

    def test_fields_nullable(self) -> None:
        q = _make_query(
            return_kind=ReturnKind.MANY,
            fields=(Field("id", _INT, True),),
        )
        source = render_module([q], "sql")
        assert "id: int | None = None" in source

    def test_fields_non_nullable(self) -> None:
        q = _make_query(
            return_kind=ReturnKind.MANY,
            fields=(Field("id", _INT, False),),
        )
        source = render_module([q], "sql")
        assert "id: int" in source

    def test_uses_conn_fetch(self) -> None:
        q = _make_query(return_kind=ReturnKind.MANY, fields=(Field("id", _INT, True),))
        source = render_module([q], "sql")
        assert "conn.fetch" in source

    def test_returns_list(self) -> None:
        q = _make_query(return_kind=ReturnKind.MANY, fields=(Field("id", _INT, True),))
        source = render_module([q], "sql")
        assert "list[FindUserRow]" in source


class TestRenderOneQuery:
    def test_uses_conn_fetchrow(self) -> None:
        q = _make_query(
            return_kind=ReturnKind.ONE,
            fields=(Field("id", _INT, True),),
        )
        source = render_module([q], "sql")
        assert "conn.fetchrow" in source

    def test_returns_optional(self) -> None:
        q = _make_query(
            return_kind=ReturnKind.ONE,
            fields=(Field("id", _INT, True),),
        )
        source = render_module([q], "sql")
        assert "FindUserRow | None" in source

    def test_handles_null_row(self) -> None:
        q = _make_query(
            return_kind=ReturnKind.ONE,
            fields=(Field("id", _INT, True),),
        )
        source = render_module([q], "sql")
        assert "if _row is None:" in source
        assert "return None" in source


class TestRenderExecQuery:
    def test_no_row_model_class(self) -> None:
        q = _make_query(
            return_kind=ReturnKind.EXEC,
            sql="insert into users (email) values ($1)",
            params=(Param("_1", _STR, True),),
            fields=(),
            row_model_name="",
        )
        source = render_module([q], "sql")
        assert "class " not in source or "BaseModel" not in source.split("async def")[1]

    def test_uses_conn_execute(self) -> None:
        q = _make_query(
            return_kind=ReturnKind.EXEC,
            sql="insert into users (email) values ($1)",
            params=(Param("_1", _STR, True),),
            fields=(),
            row_model_name="",
        )
        source = render_module([q], "sql")
        assert "conn.execute" in source

    def test_returns_none(self) -> None:
        q = _make_query(
            return_kind=ReturnKind.EXEC,
            sql="insert into users (email) values ($1)",
            params=(Param("_1", _STR, True),),
            fields=(),
            row_model_name="",
        )
        source = render_module([q], "sql")
        assert "-> None:" in source

    def test_no_pydantic_import_for_exec_only(self) -> None:
        """When all queries are EXEC, no pydantic import is needed."""
        q = _make_query(
            return_kind=ReturnKind.EXEC,
            sql="insert into t values ($1)",
            params=(Param("_1", _STR, True),),
            fields=(),
            row_model_name="",
        )
        source = render_module([q], "sql")
        assert "pydantic" not in source


class TestRenderMultipleQueries:
    def test_both_row_models(self) -> None:
        q1 = _make_query(
            name="find_user",
            return_kind=ReturnKind.ONE,
            fields=(Field("id", _INT, True),),
        )
        q2 = _make_query(
            name="list_posts",
            return_kind=ReturnKind.MANY,
            fields=(Field("title", _STR, True),),
            row_model_name="ListPostsRow",
        )
        source = render_module([q1, q2], "sql")
        assert "class FindUserRow(BaseModel):" in source
        assert "class ListPostsRow(BaseModel):" in source

    def test_both_functions(self) -> None:
        q1 = _make_query(
            name="find_user",
            return_kind=ReturnKind.ONE,
            fields=(Field("id", _INT, True),),
        )
        q2 = _make_query(
            name="list_posts",
            return_kind=ReturnKind.MANY,
            fields=(Field("title", _STR, True),),
            row_model_name="ListPostsRow",
        )
        source = render_module([q1, q2], "sql")
        assert "async def find_user(" in source
        assert "async def list_posts(" in source


class TestRenderImportsCollected:
    def test_extra_imports_included(self) -> None:
        q = _make_query(
            fields=(Field("id", _UUID, True),),
        )
        source = render_module([q], "sql")
        assert "from uuid import UUID" in source

    def test_param_imports_included(self) -> None:
        q = _make_query(
            params=(Param("_1", _UUID, True),),
            fields=(Field("id", _INT, True),),
        )
        source = render_module([q], "sql")
        assert "from uuid import UUID" in source


class TestRenderDoc:
    def test_doc_in_function(self) -> None:
        q = _make_query(
            doc="Find a user by ID.",
            fields=(Field("id", _INT, True),),
        )
        source = render_module([q], "sql")
        assert '"""Find a user by ID."""' in source

    def test_doc_in_row_model(self) -> None:
        q = _make_query(
            doc="A user record.",
            fields=(Field("id", _INT, True),),
        )
        source = render_module([q], "sql")
        # The doc appears in both the row model class and the function
        assert source.count('"""A user record."""') >= 1


class TestRenderSqlConstant:
    def test_sql_body_in_constant(self) -> None:
        q = _make_query(
            name="get_user",
            sql="select id, name\nfrom users\nwhere id = $1",
            fields=(Field("id", _INT, True),),
        )
        source = render_module([q], "sql")
        assert "_GET_USER_SQL" in source
        assert "select id, name" in source
        assert "from users" in source


class TestRenderParamsNullable:
    def test_nullable_param_has_default(self) -> None:
        q = _make_query(
            params=(Param("_1", _STR, True),),
            fields=(Field("id", _INT, True),),
        )
        source = render_module([q], "sql")
        assert "_1: str | None = None" in source

    def test_non_nullable_param_no_default(self) -> None:
        q = _make_query(
            params=(Param("_1", _STR, False),),
            fields=(Field("id", _INT, True),),
        )
        source = render_module([q], "sql")
        assert "_1: str," in source
        # Ensure no "= None" for this param
        lines = source.split("\n")
        param_lines = [line for line in lines if "_1: str" in line]
        assert all("= None" not in line for line in param_lines)
