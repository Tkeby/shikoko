"""Typer-based CLI with ``generate`` and ``check`` subcommands."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import cast

import asyncpg
import typer

from shikoko.config import ConnectionSettings, resolve_project
from shikoko.errors import ShikokoError
from shikoko.introspect.connection import connect_pool

app = typer.Typer(
    name="shikoko",
    help="Type-safe Python code generator for PostgreSQL queries.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        from shikoko import __version__

        typer.echo(f"shikoko {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        None,
        "--version",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """shikoko — type-safe SQL for Python."""


async def _generate_pipeline(project_root: Path, conn_info: ConnectionSettings) -> None:
    """Full generate pipeline: discover → parse → prepare → render → write."""
    from collections import defaultdict

    from shikoko.check import compute_source_hash
    from shikoko.codegen.format import format_source
    from shikoko.codegen.render import render_module
    from shikoko.discovery import find_sql_files
    from shikoko.introspect.catalog import CatalogCache
    from shikoko.introspect.prepare import TypeResolver, build_query_ir
    from shikoko.parser import parse_sql_file

    sql_files = find_sql_files(project_root)
    if not sql_files:
        typer.echo("No .sql files found under any sql/ directory.")
        return

    typer.echo(f"Found {len(sql_files)} query file(s).")

    # Group by sql/ directory.
    by_dir: dict[Path, list[Path]] = defaultdict(list)
    for sql_dir, fpath in sql_files:
        by_dir[sql_dir].append(fpath)

    async with connect_pool(conn_info) as pool, pool.acquire() as conn:
        typed_conn = cast(asyncpg.Connection, conn)
        catalog = CatalogCache(typed_conn)
        resolver = TypeResolver(catalog)
        for sql_dir, files in sorted(by_dir.items()):
            queries_ir = []
            for fpath in sorted(files):
                typer.echo(f"  Introspecting {fpath.relative_to(project_root)}…")
                parsed = parse_sql_file(fpath)
                ir = await build_query_ir(typed_conn, parsed, resolver)
                queries_ir.append(ir)

            source_label = str(sql_dir.relative_to(project_root))
            source_hash = compute_source_hash(files)
            source = render_module(queries_ir, source_label, source_hash=source_hash)
            source = await format_source(source)

            # Write sql_generated.py next to the sql/ directory.
            output_path = sql_dir.parent / "sql_generated.py"
            output_path.write_text(source, encoding="utf-8")
            typer.echo(f"  Wrote {output_path.relative_to(project_root)}")

    typer.echo("Done.")


@app.command()
def generate(
    root: Path | None = typer.Option(
        None,
        "--root",
        help="Project root directory. Defaults to current working directory.",
        exists=False,
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="PostgreSQL connection string. Overrides DATABASE_URL env var.",
    ),
) -> None:
    """Connect to Postgres, introspect queries, and write generated Python."""
    project = resolve_project(root=root, database_url=database_url)
    conn_info = project.connection

    if not conn_info.database:
        typer.echo(
            "Error: no database name resolved. Use --database-url, set "
            "DATABASE_URL, PGDATABASE, or run from a directory with a "
            "pyproject.toml.",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo(f"Connecting to {conn_info.host}:{conn_info.port}/{conn_info.database}…")
    asyncio.run(_generate_pipeline(project.root, conn_info))


@app.command()
def check(
    root: Path | None = typer.Option(
        None,
        "--root",
        help="Project root directory. Defaults to current working directory.",
        exists=False,
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="PostgreSQL connection string. Overrides DATABASE_URL env var.",
    ),
) -> None:
    """Regenerate to a temp location and diff against existing files.

    Exits 0 when generated files are byte-identical, exits 1 with a diff on
    stderr otherwise.
    """
    from shikoko.check import check_pipeline

    project = resolve_project(root=root, database_url=database_url)
    conn_info = project.connection

    if not conn_info.database:
        typer.echo(
            "Error: no database name resolved. Use --database-url, set "
            "DATABASE_URL, PGDATABASE, or run from a directory with a "
            "pyproject.toml.",
            err=True,
        )
        raise typer.Exit(code=1)

    result = asyncio.run(check_pipeline(project.root, conn_info))

    if result.stale:
        for path in result.stale:
            typer.echo(f"stale: {path} (no corresponding sql/ directory)", err=True)

    if result.missing:
        for path in result.missing:
            typer.echo(f"missing: {path}", err=True)

    for _path, diff in sorted(result.diffs.items()):
        typer.echo(diff, err=False)

    if not result.matches:
        raise typer.Exit(code=1)

    typer.echo("All generated files are up to date.")


def main() -> None:
    """CLI entry point — wraps typer with top-level error handling."""
    try:
        app()
    except ShikokoError as exc:
        typer.echo(f"Error: {exc}", err=True)
        sys.exit(1)
