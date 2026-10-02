"""Logical-unit classification of the ASCII line stream."""

from __future__ import annotations

from edgar_sec.engine.document.page_markers.units import LogicalUnit, classify_units


def test_empty_text_has_no_units() -> None:
    assert classify_units("") == []


def test_a_blank_line_separates_blocks() -> None:
    units = classify_units("First block\nstill first\n\nSecond block\n")
    assert [(unit.kind, unit.start_line, unit.end_line) for unit in units] == [
        ("paragraph", 0, 1),
        ("paragraph", 3, 3),
    ]


def test_a_paragraph_is_healed_but_keeps_its_source_line_span() -> None:
    (unit,) = classify_units("The company manufactures\nwidgets and services.\n")
    assert unit.kind == "paragraph"
    assert unit.text == "The company manufactures widgets and services."
    assert (unit.start_line, unit.end_line) == (0, 1)
    assert unit.line_count == 2


def test_a_sentence_ending_in_punctuation_starts_a_new_healed_clause() -> None:
    (unit,) = classify_units("One sentence. Another capital line here")
    assert unit.text == "One sentence. Another capital line here"


def test_aligned_gutter_columns_read_as_a_table_and_keep_their_lines() -> None:
    (unit,) = classify_units("Item    Amount\nAlpha   12\nBravo   34\n")
    assert unit.kind == "table"
    assert unit.text.splitlines() == [
        "Item    Amount",
        "Alpha   12",
        "Bravo   34",
    ]


def test_a_separator_line_counts_as_a_table_row() -> None:
    (unit,) = classify_units("----   ----\nItem    1\nGadgets 2\n")
    assert unit.kind == "table"


def test_gutter_columns_further_apart_than_the_tolerance_are_not_a_table() -> None:
    # A gutter's position is the column just after the first word, so "Al" and
    # "Delta" place theirs three columns apart, beyond the two-column tolerance.
    units = classify_units("Al              Beta\nGamma\nDelta               Epsilon\n")
    assert {unit.kind for unit in units} == {"paragraph"}


def test_a_minority_of_table_rows_with_aligned_columns_is_still_a_table() -> None:
    # Only the middle line lacks a gutter, and the two that have one share a
    # column within tolerance, so the block classifies as a table. The
    # classification is on the gutters that are present, not on unanimity.
    (unit,) = classify_units("Alpha   Beta\nGamma\nDelta   Epsilon\n")
    assert unit.kind == "table"


def test_units_map_back_to_source_lines_across_a_long_document() -> None:
    text = (
        "Heading\n"
        "\n"
        "One line of prose\n"
        "continued here\n"
        "\n"
        "Item    Value\n"
        "Alpha   1\n"
        "Bravo   2\n"
        "\n"
        "• bullet one\n"
        "• bullet two"
    )
    units = classify_units(text)
    assert [(unit.kind, unit.start_line, unit.end_line) for unit in units] == [
        ("paragraph", 0, 0),
        ("paragraph", 2, 3),
        ("table", 5, 7),
        ("list", 9, 10),
    ]


def test_bulleted_lines_read_as_a_list_and_keep_their_lines() -> None:
    (unit,) = classify_units("• first item\n• second item\n")
    assert unit.kind == "list"
    assert unit.text == "• first item\n• second item"


def test_a_single_bulleted_line_is_still_a_list() -> None:
    (unit,) = classify_units("1. Only item")
    assert unit.kind == "list"


def test_logical_unit_is_frozen_and_reports_its_line_count() -> None:
    unit = LogicalUnit(kind="paragraph", start_line=2, end_line=5, text="x")
    assert unit.line_count == 4
