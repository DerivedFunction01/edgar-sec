"""Representation-neutral cover healing on normalized text frames."""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.domain.forms.common.checkmarks import CheckmarkScope
from edgar_sec.engine.document.page_markers.detector import is_page_marker_line
from edgar_sec.engine.forms.cover.healing.binary_blocks import (
    merge_yes_no_binary_blocks,
    normalize_checkbox_tokens,
)
from edgar_sec.engine.forms.cover.models import CoverBoundary
from edgar_sec.engine.forms.cover.reflow import (
    is_checkbox_answer_line,
    is_cover_layout_line,
)
from edgar_sec.engine.reflow.engine.rewrapper import reflow_ascii
from edgar_sec.engine.reflow.types import ReflowPolicy
from edgar_sec.engine.tables.protection.tags import (
    SENTINEL_PREFIX,
    SENTINEL_SUFFIX,
    mask_tagged_tables,
    restore_tagged_tables,
)
from edgar_sec.foundation.text.dates import heal_date_fragments
from edgar_sec.foundation.text.healing import PhraseSequenceRule, heal_split_lines


def heal_cover_text(
    text: str,
    boundary: CoverBoundary,
    healing_rules: Sequence[PhraseSequenceRule],
    *,
    merge_binary_blocks: bool = False,
    reflow_prose: bool = True,
) -> tuple[str, bool]:
    """Apply configured healing to the bounded cover slice only; tagged tables are
    opaque, and the boolean reports whether the text changed.
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
    healed_cover_lines = (
        merge_yes_no_binary_blocks(
            masked_cover_lines,
            scope=CheckmarkScope.GLOBAL_SAFE,
        )
        if merge_binary_blocks
        else masked_cover_lines
    )
    # reflow_prose is a dormant upgrade path over phrase healing; production callers
    # pass False until the cover boundary/table interactions are resolved.
    if reflow_prose:
        reflowed = reflow_ascii(
            "\n".join(healed_cover_lines),
            body_start_line=0,
            policy=ReflowPolicy(
                unwrap_pre_body_prose=True,
                relax_prose_layout_gaps=True,
                unwrap_bullet_continuations=True,
                is_checkbox_answer_line=is_checkbox_answer_line,
                is_page_boundary_line=is_page_marker_line,
                is_structural_line=is_cover_layout_line,
            ),
        )
        healed_cover_lines = reflowed.text.splitlines()
    elif healing_rules:
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

    # Pass A (global-safe tokens) runs over the healed slice including restored
    # tables: masked content never reached line normalization, so cover tables
    # would keep raw Wingdings artifacts otherwise.
    healed_cover = normalize_checkbox_tokens(healed_cover)
    healed = "\n".join([healed_cover] + body_lines) if body_lines else healed_cover
    return healed, healed != text


__all__ = ["heal_cover_text"]
