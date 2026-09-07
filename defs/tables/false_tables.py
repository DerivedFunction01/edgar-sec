"""Post-table extraction cleanup and false/layout table unwrapping.

The default :func:`cleanup_false_tables` pass unwraps the dominant
layout-only HTML table cases: a rendered ``<TABLE>`` block whose visible
text fits on a single line (often a single bulleted risk-factor row, a
checkbox row, or a one-line prose fragment) rather than a structured
multi-line table. Consecutive unwrapped tables join onto a single
separated line, with a single newline between bullet/list items so they
remain readable as a list rather than collapsing into a single sentence
or producing extra blank lines.

Tables are intentionally retained when:
 * they have more than one visible text line (multi-row financial
   statements, multi-cell data tables, signatory blocks, etc.);
 * their visible text starts with ``ITEM `` or ``PART `` (cover/TOC
   detection still uses them); or
 * the rendered text contains only numeric separator characters
   (financial-statement-like layouts).
"""

from __future__ import annotations

import re

from defs.text.tokens import BULLET_MARKER_RE

_RE_TABLE_BLOCK = re.compile(r"<TABLE>.*?</TABLE>", re.DOTALL)
_RE_HEADING_PREFIX = re.compile(r"^\s*(?:ITEM|PART)\s+[IVX0-9]", re.IGNORECASE)
_RE_NUMERIC_SEPARATOR = re.compile(r"^[-=\s]+$")


def _visible_text(block: str) -> str:
    inner = block[len("<TABLE>") : -len("</TABLE>")]
    lines = [line.strip() for line in inner.splitlines() if line.strip()]
    return " ".join(lines)


def is_false_table(table_body: str) -> bool:
    """Return True for single-line tables that should be unwrapped."""
    inner = table_body[len("<TABLE>") : -len("</TABLE>")]
    lines = [line.strip() for line in inner.splitlines() if line.strip()]
    if len(lines) != 1:
        return False
    text = lines[0]
    if not text:
        return False
    if _RE_HEADING_PREFIX.match(text):
        return False
    return not _RE_NUMERIC_SEPARATOR.match(text)


def _is_list_item(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    first_token = stripped.split(maxsplit=1)[0]
    return bool(BULLET_MARKER_RE.match(first_token))


def _unwrap_block(block: str) -> str:
    return _visible_text(block)


def cleanup_false_tables(text: str) -> str:
    """Unwrap layout-only single-line tables without dropping surrounding text."""
    if "<TABLE>" not in text:
        return text

    replacements: dict[str, str] = {}
    for block in _RE_TABLE_BLOCK.findall(text):
        if is_false_table(block):
            replacements[block] = _unwrap_block(block)

    if not replacements:
        return text

    pattern = re.compile("|".join(re.escape(block) for block in replacements), re.DOTALL)
    pieces: list[str] = []
    last = 0
    previous_unwrapped: str | None = None

    for match in pattern.finditer(text):
        gap = text[last : match.start()]
        block = match.group(0)
        unwrapped = replacements[block]

        if previous_unwrapped is not None and not gap.strip():
            if _is_list_item(previous_unwrapped) or _is_list_item(unwrapped):
                if pieces:
                    pieces[-1] = pieces[-1].rstrip()
                pieces.append("\n")
            else:
                if pieces and not pieces[-1].endswith((" ", "\n")):
                    pieces.append(" ")
        else:
            pieces.append(gap)

        pieces.append(unwrapped)
        previous_unwrapped = unwrapped
        last = match.end()

    pieces.append(text[last:])
    return "".join(pieces).strip()


__all__ = ["cleanup_false_tables", "is_false_table"]
