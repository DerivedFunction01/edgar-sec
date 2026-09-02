"""Contract tests for ASCII logical-unit classification."""

from __future__ import annotations

import importlib

import pytest

lu_mod = importlib.import_module("defs.text.logical_units")

classify_units = lu_mod.classify_units
units_after = lu_mod.units_after
line_offset = lu_mod.line_offset
LogicalUnit = lu_mod.LogicalUnit


def test_paragraphs_split_on_double_newline() -> None:
    text = "First paragraph line one.\nFirst paragraph line two.\n\nSecond paragraph.\n"
    units = classify_units(text)
    assert len(units) == 2
    assert units[0].kind == "paragraph"
    assert "First paragraph line one" in units[0].text
    assert "First paragraph line two" in units[0].text
    assert units[1].kind == "paragraph"
    assert "Second paragraph" in units[1].text


def test_soft_wraps_joined_in_paragraph() -> None:
    text = (
        "The Company was incorporated in Delaware in 1985 and manufactures widgets for\n"
        "industrial customers throughout North America and Europe. It provides products\n"
        "to customers worldwide.\n"
    )
    units = classify_units(text)
    assert len(units) == 1
    assert units[0].kind == "paragraph"
    assert "\n" not in units[0].text
    assert "manufactures widgets for industrial customers" in units[0].text


def test_table_rows_classified_as_table() -> None:
    text = (
        "Column A      Column B      Column C\n"
        "---------     ---------     ---------\n"
        "Value 1       100           200\n"
        "Value 2       300           400\n"
    )
    units = classify_units(text)
    assert len(units) == 1
    assert units[0].kind == "table"


def test_bulleted_list_classified_as_list() -> None:
    text = (
        "- First item in the list\n"
        "- Second item in the list\n"
        "- Third item in the list\n"
    )
    units = classify_units(text)
    assert len(units) == 1
    assert units[0].kind == "list"


def test_empty_text_returns_empty() -> None:
    assert classify_units("") == []


def test_blank_lines_skipped() -> None:
    text = "\n\n\nOnly paragraph.\n\n\n"
    units = classify_units(text)
    assert len(units) == 1
    assert units[0].text == "Only paragraph."


def test_units_after_filters_by_line() -> None:
    text = "Line zero.\n\nLine two.\n\nLine four.\n"
    units = classify_units(text)
    filtered = units_after(units, 2)
    assert all(unit.start_line >= 2 for unit in filtered)


def test_line_offset_computes_character_position() -> None:
    lines = ["hello", "world", "foo"]
    assert line_offset(lines, 0) == 0
    assert line_offset(lines, 1) == 6
    assert line_offset(lines, 2) == 12


def test_logical_unit_is_frozen() -> None:
    unit = LogicalUnit(kind="paragraph", start_line=0, end_line=1, text="hello world")
    assert unit.line_count == 2
    with pytest.raises(AttributeError):
        unit.kind = "table"  # type: ignore[misc]


def test_mixed_document_classification() -> None:
    text = (
        "The Company was incorporated in Delaware and manufactures widgets for\n"
        "industrial customers throughout North America and Europe.\n\n"
        "Column A      Column B\n"
        "---------     ---------\n"
        "Value 1       100\n"
        "Value 2       200\n\n"
        "- First bullet item\n"
        "- Second bullet item\n\n"
        "Final paragraph after the list.\n"
    )
    units = classify_units(text)
    kinds = [unit.kind for unit in units]
    assert kinds == ["paragraph", "table", "list", "paragraph"]
