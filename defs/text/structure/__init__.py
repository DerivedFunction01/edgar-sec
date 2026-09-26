"""Document layout and structural classification.

Non-mutating classification of ASCII lines, paragraphs, and tables, plus the
domain-neutral line-shape patterns those classifiers compose. This layer sits
directly above ``defs.text.syntax`` and stays free of form- or document-type
vocabulary; callers own their own predicates.

Modules:

- ``patterns``: domain-neutral line shapes (gutters, dot leaders, rules).
- ``logical_units``: ASCII paragraph/table/list unit boundary classification.
- ``counts``: allocation-free ``count_words`` and ``count_lines``.
"""

from __future__ import annotations

from .counts import count_lines, count_words
from .logical_units import (
    LogicalUnit,
    classify_units,
    line_offset,
    units_after,
)
from .patterns import (
    CONTINUATION_PUNCTUATION,
    PAGE_NUMBER_CORE,
    RE_COLUMN_GAP,
    RE_CONFORMED_SIGNATURE,
    RE_DOT_LEADER,
    RE_FILL_IN_RUN,
    RE_GRAMMATICAL_COMMA,
    RE_NON_ALNUM,
    RE_PAGE_NUMBER_SUFFIX,
    RE_SENTENCE_TERMINAL,
    RE_SEPARATOR_LINE,
    RE_SEPARATOR_RUN,
    RE_SIGNATURE_LABEL_LINE,
    RE_STRUCTURAL_SGML,
    RE_TERMINAL_BOUNDARY,
    RE_TRAILING_FILL_IN,
    RE_WHITESPACE,
    SIGNATURE_LABEL_PREFIXES,
)

__all__ = [
    "CONTINUATION_PUNCTUATION",
    "PAGE_NUMBER_CORE",
    "RE_COLUMN_GAP",
    "RE_CONFORMED_SIGNATURE",
    "RE_DOT_LEADER",
    "RE_FILL_IN_RUN",
    "RE_GRAMMATICAL_COMMA",
    "RE_NON_ALNUM",
    "RE_PAGE_NUMBER_SUFFIX",
    "RE_SENTENCE_TERMINAL",
    "RE_SEPARATOR_LINE",
    "RE_SEPARATOR_RUN",
    "RE_SIGNATURE_LABEL_LINE",
    "RE_STRUCTURAL_SGML",
    "RE_TERMINAL_BOUNDARY",
    "RE_TRAILING_FILL_IN",
    "RE_WHITESPACE",
    "SIGNATURE_LABEL_PREFIXES",
    "LogicalUnit",
    "classify_units",
    "count_lines",
    "count_words",
    "line_offset",
    "units_after",
]
