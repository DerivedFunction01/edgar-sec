"""Unit tests for edgar_sec.engine.tables.table_policy."""

from __future__ import annotations

from edgar_sec.engine.tables.table_policy import (
    is_table_row_continuation,
    is_tableish_block,
    split_structural_table_intro,
)


def test_split_structural_table_intro() -> None:
    lines = (
        "The following table presents our revenues:",
        "Revenue by segment       2024       2023",
        "  Automotive             $1,200     $1,100",
        "  Industrial             $2,300     $2,050",
    )
    intro, table = split_structural_table_intro(lines)
    assert intro == ("The following table presents our revenues:",)
    assert len(table) == 3


def test_is_tableish_block() -> None:
    table_lines = (
        "Revenue by segment       2024       2023",
        "  Automotive             $1,200     $1,100",
        "  Industrial             $2,300     $2,050",
    )
    assert is_tableish_block(table_lines)

    prose_lines = (
        "We are an enterprise software company founded in 1998",
        "that sells products across multiple market segments today.",
    )
    assert not is_tableish_block(prose_lines)


def test_is_table_row_continuation() -> None:
    prev = (
        "Revenue by segment       2024       2023",
        "  Automotive             $1,200     $1,100",
    )
    cont = ("  Industrial             $2,300     $2,050",)
    assert is_table_row_continuation(prev, cont)
