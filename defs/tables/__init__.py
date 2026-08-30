"""Structured table extraction, ASCII formatting, and row-healing tools."""

from __future__ import annotations

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
from .processor import SimpleTableProcessor, process_table
from .table_definitions import (
    GenericTable,
    HTMLTableConverter,
    convert_html_tables_to_ascii,
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
    "GenericTable",
    "HTMLTableConverter",
    "SimpleTableProcessor",
    "convert_html_tables_to_ascii",
    "is_financial_placeholder",
    "is_numeric_cell",
    "is_numeric_start",
    "is_prefix_token",
    "is_suffix_token",
    "process_table",
]
