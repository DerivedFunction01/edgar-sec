"""Representation-neutral cover healing on normalized text frames."""

from __future__ import annotations

import re
from collections.abc import Sequence

from edgar_sec.domain.forms.checkmarks import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
    RE_RAW_CHECKED,
    RE_RAW_UNCHECKED,
)
from edgar_sec.engine.forms.cover.models import CoverBoundary
from edgar_sec.engine.forms.cover.reflow import (
    is_checkbox_answer_line,
    is_cover_layout_line,
    is_page_marker_line,
)
from edgar_sec.engine.reflow.engine import reflow_ascii
from edgar_sec.engine.reflow.types import ReflowPolicy
from edgar_sec.engine.tables.protection import (
    SENTINEL_PREFIX,
    SENTINEL_SUFFIX,
    mask_tagged_tables,
    restore_tagged_tables,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import heal_date_fragments
from edgar_sec.foundation.text.healing import PhraseSequenceRule, heal_split_lines

_BARE_CHECKED = ("x", "X")
_RE_BARE_CHECKED = re.compile(
    rf"(?<!\S)(?:{build_alternation(_BARE_CHECKED, auto_escape=True)})(?!\S)",
    re.IGNORECASE,
)
_RE_BRACKET_CHECKED = re.compile(r"(\[[Xx]\])(?=[A-Za-z0-9])")
_RE_BRACKET_CHECKED_AFTER = re.compile(r"([A-Za-z0-9])(\[[Xx]\])")
_RE_BRACKET_UNCHECKED = re.compile(r"(\[ \])(?=[A-Za-z0-9])")
_RE_BRACKET_UNCHECKED_AFTER = re.compile(r"([A-Za-z0-9])(\[ \])")
_RE_PAREN_CHECKED = re.compile(r"(\([Xx]\))(?=[A-Za-z0-9])")
_RE_PAREN_CHECKED_AFTER = re.compile(r"([A-Za-z0-9])(\([Xx]\))")


def normalize_checkbox_tokens(text: str) -> str:
    """Normalize safe checkbox tokens."""
    text = RE_RAW_CHECKED.sub(CANONICAL_CHECKED, text)
    text = RE_RAW_UNCHECKED.sub(CANONICAL_UNCHECKED, text)
    text = _RE_BARE_CHECKED.sub(CANONICAL_CHECKED, text)
    text = _RE_BRACKET_CHECKED.sub(f"{CANONICAL_CHECKED} ", text)
    text = _RE_BRACKET_CHECKED_AFTER.sub(rf"\1 {CANONICAL_CHECKED}", text)
    text = _RE_BRACKET_UNCHECKED.sub(f"{CANONICAL_UNCHECKED} ", text)
    text = _RE_BRACKET_UNCHECKED_AFTER.sub(rf"\1 {CANONICAL_UNCHECKED}", text)
    text = _RE_PAREN_CHECKED.sub(f"{CANONICAL_CHECKED} ", text)
    text = _RE_PAREN_CHECKED_AFTER.sub(rf"\1 {CANONICAL_CHECKED}", text)
    return text


def heal_cover_text(
    text: str,
    boundary: CoverBoundary,
    healing_rules: Sequence[PhraseSequenceRule] = (),
    *,
    merge_binary_blocks: bool = False,
    reflow_prose: bool = False,
) -> tuple[str, bool]:
    """Apply configured healing only to the bounded cover line slice.

    Tagged tables are opaque during healing. The returned boolean indicates
    whether the text changed and lets callers refresh line-coordinate analyses.
    """
    if boundary.end_line is None:
        return text, False

    lines = text.splitlines()
    cover_lines = lines[: boundary.end_line]
    body_lines = lines[boundary.end_line :]
    cover_text = "\n".join(cover_lines)

    masked_cover, table_spans = mask_tagged_tables(cover_text)
    masked_cover_lines = masked_cover.splitlines()

    healed_cover_lines = masked_cover_lines
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

    healed_cover = normalize_checkbox_tokens(healed_cover)
    healed = "\n".join([healed_cover] + body_lines) if body_lines else healed_cover
    return healed, healed != text


__all__ = ["heal_cover_text", "normalize_checkbox_tokens"]
