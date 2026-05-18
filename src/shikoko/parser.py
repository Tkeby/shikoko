"""Parse ``.sql`` files into :class:`ParsedQuery` objects."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from shikoko.errors import QueryParseError, UnknownAnnotationError

# Annotations we understand.
_KNOWN_ANNOTATIONS = frozenset({"one", "exec"})
_ANNOTATION_RE = re.compile(r"^--\s*@(\w+)(?::\s*(.+))?$")


@dataclass(frozen=True)
class ParsedQuery:
    """A single SQL query extracted from a ``.sql`` file."""

    name: str
    doc: str
    body: str
    annotations: dict[str, str] = field(default_factory=dict)
    source_file: Path = field(default_factory=Path)
    source_line: int = 0


def parse_sql_file(path: Path) -> ParsedQuery:
    """Parse a ``.sql`` file into a :class:`ParsedQuery`.

    Leading ``--`` lines form the docstring and may contain annotations.
    Everything after the leading comment block is the query body.

    Raises:
        QueryParseError: if the file has no non-comment content.
        UnknownAnnotationError: if an unknown ``-- @`` annotation is found.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    doc_lines: list[str] = []
    annotations: dict[str, str] = {}
    first_body_line = len(lines)  # 1-based line where body starts

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Check if this is a comment line.
        if stripped.startswith("--"):
            # Inside the leading comment block — check for annotations.
            if not doc_lines and not stripped.startswith("--"):
                # blank before first comment
                continue

            m = _ANNOTATION_RE.match(stripped)
            if m:
                key = m.group(1)
                value = (m.group(2) or "").strip()

                if key == "name":
                    annotations["name"] = value
                elif key in _KNOWN_ANNOTATIONS:
                    annotations["return_kind"] = key
                else:
                    raise UnknownAnnotationError(
                        file=path,
                        line=i + 1,
                        annotation=key,
                    )
            else:
                # Regular comment line — strip the ``-- `` prefix for the doc.
                content = stripped[2:].lstrip(" ")
                doc_lines.append(content)

            continue

        # Non-comment, non-empty line — end of leading comment block.
        if stripped:
            first_body_line = i
            break

        # Blank line inside the leading comment block area.
        if not doc_lines and not annotations:
            continue

        # Blank line after we've started collecting comments — could be
        # a separator between comment paragraphs. Keep going; we treat
        # leading blank lines before any comment as not part of the block.
        if doc_lines or annotations:
            continue

    # Body is everything from first_body_line onward.
    body_lines = lines[first_body_line:]
    body = "\n".join(body_lines).strip()

    if not body:
        raise QueryParseError(
            file=path,
            line=1,
            message="file contains no SQL statement",
        )

    doc = "\n".join(doc_lines).strip()
    name = annotations.pop("name", path.stem)

    return ParsedQuery(
        name=name,
        doc=doc,
        body=body,
        annotations=annotations,
        source_file=path,
        source_line=first_body_line + 1,
    )
