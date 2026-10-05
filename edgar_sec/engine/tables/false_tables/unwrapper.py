"""Rebuilding prose from a layout grid the detector rejected.
A retained table's bytes are never touched; an unwrapped grid becomes readable text, and
consecutive grids join as the prose around them would.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from edgar_sec.foundation.text.patterns import CONTINUATION_PUNCTUATION
from edgar_sec.foundation.text.tokens import BULLET_MARKER_RE

from ..patterns import RE_TABLE_BLOCK
from .detector import _marker_candidates, _visible_text, is_false_table

if TYPE_CHECKING:
    from ..ascii_html.model import TableGeometry

_RE_TABLE_BLOCK = RE_TABLE_BLOCK


def _is_list_item(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    first_token = stripped.split(maxsplit=1)[0]
    return bool(BULLET_MARKER_RE.match(first_token))


def _join_prose_rows(rows: list[list[str]]) -> str:
    """Join logical prose rows, breaking after complete list items."""
    texts = [" ".join(row) for row in rows]
    pieces: list[str] = []
    for index, text in enumerate(texts):
        if index > 0:
            previous = texts[index - 1].rstrip()
            pieces.append("\n" if previous.endswith(CONTINUATION_PUNCTUATION) else " ")
        pieces.append(text)
    return "".join(pieces)


def unwrap_grid(grid_rows: Sequence[Sequence[str]]) -> str:
    """Unwrap a false grid into formatted prose or bullet text."""
    rows: list[list[str]] = []
    has_markers = False
    for raw_row in grid_rows:
        row: list[str] = []
        for cell in raw_row:
            stripped = cell.strip()
            if not stripped:
                continue
            row.append(stripped)
            if not has_markers and (
                BULLET_MARKER_RE.match(stripped) or bool(_marker_candidates(stripped))
            ):
                has_markers = True
        if row:
            rows.append(row)

    if not rows:
        return ""
    if has_markers:
        return "\n".join(" ".join(row) for row in rows)
    return _join_prose_rows(rows)


def _unwrap_block(block: str, geometry: TableGeometry | None = None) -> str:
    if geometry is not None and geometry.rows:
        return unwrap_grid(geometry.rows)
    return _visible_text(block)


def cleanup_false_tables_with_metadata(
    text: str,
    geometries: Sequence[TableGeometry] | None = None,
) -> tuple[str, tuple[TableGeometry, ...]]:
    """Unwrap layout-only single-line tables without dropping surrounding text.
    Retained: multiple visible text lines, a contents row with page numbers, or numeric separators only. Consecutive unwrapped tables join onto one line.
    """
    if "<TABLE>" not in text:
        return text, tuple(geometries or ())

    matches = list(_RE_TABLE_BLOCK.finditer(text))
    if not matches:
        return text, tuple(geometries or ())

    blocks = [m.group(0) for m in matches]
    verdicts = [
        is_false_table(
            block, geometries[i] if geometries and i < len(geometries) else None
        )
        for i, block in enumerate(blocks)
    ]
    # A footnote-like table immediately preceding a retained table may unwrap even when its
    # second-column text is label-shaped.
    for i, unwrapped in enumerate(verdicts):
        if unwrapped or i + 1 >= len(blocks) or verdicts[i + 1]:
            continue
        if text[matches[i].end() : matches[i + 1].start()].strip():
            continue
        geometry = geometries[i] if geometries and i < len(geometries) else None
        if (
            geometry is not None
            and geometry.rows
            and is_false_table(blocks[i], geometry, allow_footnote_context=True)
        ):
            verdicts[i] = True

    kept_geometries = tuple(
        geometry
        for index, geometry in enumerate(geometries or ())
        if index >= len(blocks) or not verdicts[index]
    )

    if not any(verdicts):
        return text, kept_geometries

    pieces: list[str] = []
    last = 0
    previous_unwrapped: str | None = None

    for i, match in enumerate(matches):
        gap = text[last : match.start()]
        if not verdicts[i]:
            pieces.append(gap)
            pieces.append(match.group(0))
            previous_unwrapped = None
            last = match.end()
            continue

        geometry = geometries[i] if geometries and i < len(geometries) else None
        unwrapped = _unwrap_block(match.group(0), geometry)

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
    return "".join(pieces).strip(), kept_geometries


__all__ = [
    "cleanup_false_tables_with_metadata",
    "unwrap_grid",
]
