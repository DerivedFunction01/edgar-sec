"""Text, line, phrase, and whitespace healing infrastructure.

This package owns representation-neutral text repair: soft-wrap line joining,
Yes/No binary checkbox block normalization, Cartesian compound term expansion,
and final text whitespace normalization.
"""

from __future__ import annotations

from .compounds import (
    expand_alternations,
    expand_compounds,
    expand_variants,
)
from .lines import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
    NEGATIVE_BOUNDARY_RE,
    RE_RAW_CHECKED,
    RE_RAW_UNCHECKED,
    PhraseSequenceRule,
    classify_mark_line,
    heal_split_lines,
    merge_yes_no_binary_blocks,
    normalize_checkbox_tokens,
    normalize_whitespace_and_tabs,
    should_join_two_lines,
    strip_alphanumeric_words,
    strip_boxdot_spacers,
)
from .whitespace import (
    normalize_final_text_whitespace,
    split_concatenated_bullets,
)

__all__ = [
    "CANONICAL_CHECKED",
    "CANONICAL_UNCHECKED",
    "NEGATIVE_BOUNDARY_RE",
    "RE_RAW_CHECKED",
    "RE_RAW_UNCHECKED",
    "PhraseSequenceRule",
    "classify_mark_line",
    "expand_alternations",
    "expand_compounds",
    "expand_variants",
    "heal_split_lines",
    "merge_yes_no_binary_blocks",
    "normalize_checkbox_tokens",
    "normalize_final_text_whitespace",
    "normalize_whitespace_and_tabs",
    "should_join_two_lines",
    "split_concatenated_bullets",
    "strip_alphanumeric_words",
    "strip_boxdot_spacers",
]
