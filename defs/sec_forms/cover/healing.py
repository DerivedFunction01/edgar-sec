"""Representation-neutral cover healing on normalized text frames."""

from __future__ import annotations

from collections.abc import Sequence

from defs.tables.protection import (
    SENTINEL_PREFIX,
    SENTINEL_SUFFIX,
    mask_tagged_tables,
    restore_tagged_tables,
)
from defs.text import (
    CheckmarkScope,
    heal_date_fragments,
    heal_split_lines,
    merge_yes_no_binary_blocks,
    normalize_checkbox_tokens,
)
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
    Global-safe checkbox normalization (Pass A) always runs on the slice and on
    restored table content, independent of the configured healing rules.
    """
    if boundary.end_line is None:
        return text, False

    lines = text.splitlines()
    cover_lines = lines[: boundary.end_line]
    body_lines = lines[boundary.end_line :]
    cover_text = "\n".join(cover_lines)

    masked_cover, table_spans = mask_tagged_tables(cover_text)
    masked_cover_lines = masked_cover.splitlines()

    # Ambiguous marks are resolved by the form-scoped constraint pass before
    # this layout-only stage. Do not infer state from a broad cover boundary.
    healed_cover_lines = merge_yes_no_binary_blocks(
        masked_cover_lines, scope=CheckmarkScope.GLOBAL_SAFE
    )
    if healing_rules:
        healed_cover_lines = heal_split_lines(
            healed_cover_lines, rules=tuple(healing_rules)
        )
    healed_cover_lines = heal_date_fragments(healed_cover_lines)
    healed_cover = "\n".join(healed_cover_lines)

    if table_spans:
        expected = tuple(
            f"{SENTINEL_PREFIX}{position}{SENTINEL_SUFFIX}"
            for position in range(len(table_spans))
        )
        if not all(sentinel in healed_cover for sentinel in expected):
            return text, False
        healed_cover = restore_tagged_tables(healed_cover, table_spans)

    # Pass A (global-safe tokens) runs over the whole healed cover slice,
    # including restored tagged tables: masked table content never reached the
    # line-level normalization above, so retained cover tables such as the
    # filer-status grid would keep raw Wingdings artifacts otherwise.
    healed_cover = normalize_checkbox_tokens(healed_cover)
    healed = "\n".join([healed_cover] + body_lines) if body_lines else healed_cover
    return healed, healed != text


__all__ = ["heal_cover_text"]
