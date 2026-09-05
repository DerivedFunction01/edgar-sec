"""Canonical geometry-first HTML table extraction and shared table tokens."""

from __future__ import annotations

from .ascii_html import (
    convert_html_table,
    convert_html_tables_to_ascii,
    render_grid_to_ascii,
)
from .currencies import MAJOR_CURRENCIES, PREFIX_SYMBOLS, SUFFIX_SYMBOLS
from .patterns import (
    BULLET_MARKER_RE,
    FINANCIAL_PLACEHOLDERS,
    FOOTNOTE_RE,
    HIDDEN_ELEMENT_STYLE_RE,
    NUMERIC_CELL_RE,
    PAREN_SPACES_RE,
    YEAR_TOKEN_RE,
)
from .tokens import (
    ALL_CURRENCY_SYMBOLS,
    PREFIX_TOKENS,
    SUFFIX_TOKENS,
    is_financial_placeholder,
    is_numeric_cell,
    is_numeric_start,
    is_prefix_token,
    is_suffix_token,
)

__all__ = [
    "ALL_CURRENCY_SYMBOLS",
    "BULLET_MARKER_RE",
    "FINANCIAL_PLACEHOLDERS",
    "FOOTNOTE_RE",
    "HIDDEN_ELEMENT_STYLE_RE",
    "MAJOR_CURRENCIES",
    "NUMERIC_CELL_RE",
    "PAREN_SPACES_RE",
    "PREFIX_SYMBOLS",
    "PREFIX_TOKENS",
    "SUFFIX_SYMBOLS",
    "SUFFIX_TOKENS",
    "YEAR_TOKEN_RE",
    "convert_html_table",
    "convert_html_tables_to_ascii",
    "is_financial_placeholder",
    "is_numeric_cell",
    "is_numeric_start",
    "is_prefix_token",
    "is_suffix_token",
    "render_grid_to_ascii",
]
