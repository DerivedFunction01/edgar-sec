"""Tests for ownership table cell splitting and column contracts."""

from __future__ import annotations

from edgar_sec.engine.forms.ownership.table_common import (
    extract_ownership_number,
    is_footnote_marker,
    is_nature_like,
    split_composite_underlying_cell,
    split_ownership_row_cells,
    trailing_ownership_form,
)


def test_footnote_marker_cells_are_dropped_from_a_row() -> None:
    cells = split_ownership_row_cells(
        ("Phantom Stock Unit", "(1)", "12/31/02", "A", "320"), frozenset({"1"})
    )

    assert cells == ("Phantom Stock Unit", "12/31/02", "A", "320")


def test_low_single_digit_markers_are_dropped_without_a_footnote_list() -> None:
    cells = split_ownership_row_cells(("Phantom Stock Unit", "(3)", "12/31/02"))

    assert cells == ("Phantom Stock Unit", "12/31/02")


def test_a_parenthesised_amount_is_not_a_footnote_marker() -> None:
    assert is_footnote_marker("(1,234)") is False
    assert is_footnote_marker("11") is False
    assert is_footnote_marker("(1)") is True


def test_a_footnote_marker_does_not_become_a_negative_number() -> None:
    assert extract_ownership_number("(1)") is None
    assert extract_ownership_number("320 (1)") == "320"
    assert extract_ownership_number("(1,234)") == "-1234"


def test_the_ownership_form_is_the_trailing_direct_or_indirect_value() -> None:
    index, value = trailing_ownership_form(("Common Stock", "43,697", "D"))

    assert (index, value) == (2, "D")


def test_an_acquired_disposed_code_is_not_the_ownership_form() -> None:
    index, value = trailing_ownership_form(
        ("COMMON STOCK", "03/07/03", "S", "2,749.4988", "D", "$15.29")
    )

    assert (index, value) == (-1, None)


def test_a_nature_description_follows_the_ownership_form() -> None:
    assert is_nature_like("By 401(k) Plan") is True
    assert is_nature_like("23,337.000") is False
    assert is_nature_like("$15.29") is False


def test_a_footnote_reference_beside_a_value_is_stripped() -> None:
    cells = split_ownership_row_cells(("Phantom Stock Unit", "279 (6)", "D"))

    assert cells == ("Phantom Stock Unit", "279", "D")


def test_a_composite_underlying_cell_splits_into_title_and_amount() -> None:
    cells = split_composite_underlying_cell(("Option", "Common Stock - 60,000.00", "D"))

    assert cells == ("Option", "Common Stock", "60,000.00", "D")


def test_a_composite_row_title_is_not_split() -> None:
    cells = split_composite_underlying_cell(("Common Stock - 60,000.00", "D"))

    assert cells[0] == "Common Stock - 60,000.00"


def test_a_decimal_without_an_integer_part_is_normalized() -> None:
    assert extract_ownership_number(".3235") == "0.3235"
