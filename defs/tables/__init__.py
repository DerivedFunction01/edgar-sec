"""Canonical geometry-first HTML table extraction and shared table tokens."""

from __future__ import annotations

from .ascii_html import (
    TableGeometry,
    convert_html_table,
    convert_html_tables_to_ascii,
    convert_html_tables_to_ascii_with_metadata,
    render_grid_to_ascii,
)
from .currencies import MAJOR_CURRENCIES, PREFIX_SYMBOLS, SUFFIX_SYMBOLS
from .false_tables import (
    cleanup_false_tables,
    cleanup_false_tables_with_metadata,
    is_false_table,
)
from .hybrid import (
    HybridPreText,
    PreBlockKind,
    classify_pre_block,
    normalize_hybrid_pre_blocks,
    normalize_hybrid_pre_text,
    restore_hybrid_pre_text,
)
from .patterns import (
    BULLET_MARKER_RE,
    FINANCIAL_PLACEHOLDERS,
    FOOTNOTE_RE,
    HIDDEN_ELEMENT_STYLE_RE,
    NUMERIC_CELL_RE,
    PAREN_SPACES_RE,
    YEAR_TOKEN_RE,
)
from .resolver import resolve_table_regions
from .structural import (
    is_header_prefix,
    is_structural_table_bridge,
    is_structural_table_tail,
)
from .table_policy import (
    is_table_row_continuation,
    is_tableish_block,
    split_structural_table_intro,
    unify_table_prose,
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
    "HybridPreText",
    "PreBlockKind",
    "TableGeometry",
    "classify_pre_block",
    "cleanup_false_tables",
    "cleanup_false_tables_with_metadata",
    "convert_html_table",
    "convert_html_tables_to_ascii",
    "convert_html_tables_to_ascii_with_metadata",
    "is_false_table",
    "is_financial_placeholder",
    "is_header_prefix",
    "is_numeric_cell",
    "is_numeric_start",
    "is_prefix_token",
    "is_structural_table_bridge",
    "is_structural_table_tail",
    "is_suffix_token",
    "is_table_row_continuation",
    "is_tableish_block",
    "normalize_hybrid_pre_blocks",
    "normalize_hybrid_pre_text",
    "render_grid_to_ascii",
    "resolve_table_regions",
    "restore_hybrid_pre_text",
    "split_structural_table_intro",
    "unify_table_prose",
]
