"""Representation-neutral cover healing on normalized text frames."""

from __future__ import annotations

from collections.abc import Sequence

from defs.tables.protection import mask_tagged_tables, restore_tagged_tables
from defs.text import heal_date_fragments, heal_split_lines, merge_yes_no_binary_blocks
from defs.text.healing import PhraseSequenceRule

from .models import CoverBoundary


def heal_cover_text(
    text: str,
    boundary: CoverBoundary,
    healing_rules: Sequence[PhraseSequenceRule],
) -> tuple[str, bool]:
    """Apply configured healing only to the bounded cover line slice.

    Tagged tables are opaque during healing. The returned boolean indicates
    whether the text changed and lets callers refresh line-coordinate analyses.
    """
    if boundary.end_line is None or not healing_rules:
        return text, False

    masked, table_spans = mask_tagged_tables(text)
    lines = masked.splitlines()
    cover_lines = lines[: boundary.end_line]
    body_lines = lines[boundary.end_line :]
    healed_cover = merge_yes_no_binary_blocks(cover_lines)
    healed_cover = heal_split_lines(healed_cover, rules=tuple(healing_rules))
    healed_cover = heal_date_fragments(healed_cover)
    healed = "\n".join(healed_cover + body_lines)

    if table_spans:
        expected = tuple(f"\x00{position}\x00" for position in range(len(table_spans)))
        if not all(sentinel in healed for sentinel in expected):
            return text, False
        healed = restore_tagged_tables(healed, table_spans)
    return healed, healed != text


__all__ = ["heal_cover_text"]
