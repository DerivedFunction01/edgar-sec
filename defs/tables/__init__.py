"""Structured table extraction, ASCII formatting, and row-healing tools."""

from __future__ import annotations

from .currencies import MAJOR_CURRENCIES, PREFIX_SYMBOLS, SUFFIX_SYMBOLS
from .processor import SimpleTableProcessor, process_table
from .table_definitions import GenericTable, HTMLTableConverter

__all__ = [
    "MAJOR_CURRENCIES",
    "PREFIX_SYMBOLS",
    "SUFFIX_SYMBOLS",
    "GenericTable",
    "HTMLTableConverter",
    "SimpleTableProcessor",
    "process_table",
]
