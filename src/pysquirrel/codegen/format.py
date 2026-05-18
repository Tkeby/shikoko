"""Post-generation formatting via ``ruff format``."""

from __future__ import annotations

import asyncio
import logging
import shutil

logger = logging.getLogger(__name__)


async def format_source(source: str) -> str:
    """Format *source* with ``ruff format`` if available.

    If ``ruff`` is not installed, the source is returned unchanged and a
    warning is logged.
    """
    ruff = shutil.which("ruff")
    if ruff is None:
        logger.warning("ruff not found on PATH; returning unformatted output")
        return source

    proc = await asyncio.create_subprocess_exec(
        ruff,
        "format",
        "--stdin-filename",
        "generated.py",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=source.encode("utf-8"))

    if proc.returncode != 0:
        logger.warning(
            "ruff format failed (exit %d): %s", proc.returncode, stderr.decode()
        )
        return source

    return stdout.decode("utf-8")
