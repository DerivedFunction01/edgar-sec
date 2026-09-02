"""Structural helpers for table-of-contents presentation."""

from __future__ import annotations

from defs.sec_forms.cover.structure import (
    RE_PART as PART_HEADING_RE,
)
from defs.sec_forms.cover.toc import (
    RE_TOC_ITEM as TOC_ITEM_RE,
)
from defs.sec_forms.cover.toc import (
    RE_TOC_PART_TEXT as TOC_PART_TEXT_RE,
)


def looks_like_toc_text(text: str) -> bool:
    """Recognize TOC context even when inline links split ``PART`` letters."""
    return bool("item" in text.casefold() and TOC_PART_TEXT_RE.search(text))


def toc_part_headings_are_body_rows(
    source_grid: list[list[str]], *, is_toc: bool
) -> bool:
    """Return whether part headings should stay in a TOC's body grid."""
    if not is_toc:
        return False
    values = [value.strip() for row in source_grid for value in row if value.strip()]
    return bool(
        any(PART_HEADING_RE.fullmatch(value) for value in values)
        and any(TOC_ITEM_RE.match(value) for value in values)
    )


__all__ = [
    "PART_HEADING_RE",
    "TOC_ITEM_RE",
    "TOC_PART_TEXT_RE",
    "looks_like_toc_text",
    "toc_part_headings_are_body_rows",
]
