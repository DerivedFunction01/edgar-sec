"""Unit tests for edgar_sec.engine.tables.structural."""

from __future__ import annotations

from edgar_sec.engine.tables.structural import (
    COLUMN_DASH_RULE_RE,
    COLUMN_YEAR_ROW_RE,
    UNITS_LABEL_RE,
    is_header_prefix,
    is_structural_table_bridge,
)


def test_column_dash_rule() -> None:
    assert COLUMN_DASH_RULE_RE.match("------  ------  ------") is not None
    assert COLUMN_DASH_RULE_RE.match("--- ---") is not None
    assert COLUMN_DASH_RULE_RE.match("Single dash rule line") is None


def test_units_label() -> None:
    assert UNITS_LABEL_RE.search("(in thousands)") is not None
    assert UNITS_LABEL_RE.search("(dollars in millions)") is not None
    assert UNITS_LABEL_RE.search("(shares in thousands, except per share)") is not None
    assert UNITS_LABEL_RE.search("Ordinary text") is None


def test_column_year_row() -> None:
    assert COLUMN_YEAR_ROW_RE.match("2024       2023       2022") is not None
    assert COLUMN_YEAR_ROW_RE.match("Q1 2024    Q2 2024") is not None


def test_is_header_prefix() -> None:
    assert is_header_prefix("YEAR ENDED DECEMBER 31,")
    assert is_header_prefix("   Year Ended December 31,   ")
    assert is_header_prefix("Three Months Ended 2024")


def test_is_structural_table_bridge() -> None:
    assert is_structural_table_bridge("OPERATING EXPENSES:")
    assert is_structural_table_bridge("------  ------")
    assert not is_structural_table_bridge("This is ordinary continuous prose.")
