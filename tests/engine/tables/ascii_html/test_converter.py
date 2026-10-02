"""The document-level entry points and the geometry metadata they retain."""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.ascii_html.converter import (
    convert_html_table,
    convert_html_tables_to_ascii,
    convert_html_tables_to_ascii_with_metadata,
)
from edgar_sec.engine.tables.ascii_html.model import TableGeometry
from edgar_sec.engine.tables.ascii_html.renderer import render_grid_to_ascii

DOCUMENT = """
<html><body>
  <p>Financial Statement Note</p>
  <table><tr><th><b>Line Item</b></th><th><b>Amount</b></th></tr>
  <tr><td>Revenue</td><td>1000</td></tr></table>
  <p>Second Schedule</p>
  <table><tr><th><b>Asset</b></th><th><b>Fair Value</b></th></tr>
  <tr><td>Securities</td><td>500</td></tr></table>
</body></html>
"""


def test_the_string_facade_converts_every_table_in_a_document() -> None:
    text = convert_html_tables_to_ascii(DOCUMENT)
    assert "<TABLE>" in text
    assert "Financial Statement Note" in text
    assert "Revenue" in text
    assert "Securities" in text
    assert "500" in text


def test_the_metadata_facade_returns_one_geometry_per_rendered_table() -> None:
    text, geometries = convert_html_tables_to_ascii_with_metadata(DOCUMENT)
    assert "<TABLE>" in text
    assert len(geometries) == 2
    assert all(isinstance(geometry, TableGeometry) for geometry in geometries)
    assert [geometry.table_index for geometry in geometries] == [0, 1]


def test_a_document_with_no_tables_keeps_its_text_and_has_no_geometry() -> None:
    text, geometries = convert_html_tables_to_ascii_with_metadata("<p>No tables</p>")
    assert geometries == ()
    assert "No tables" in text


def test_a_wholly_empty_table_is_decomposed_and_contributes_no_geometry() -> None:
    text, geometries = convert_html_tables_to_ascii_with_metadata(
        "<html><body><table><tr><td> </td></tr></table></body></html>"
    )
    assert geometries == ()
    assert "<TABLE>" not in text


def test_a_wholly_empty_layout_table_is_removed_entirely_in_fallback_mode() -> None:
    assert convert_html_tables_to_ascii(
        '<table cellpadding="0" cellspacing="0" style="width: 100%">'
        '<tbody><tr><td style="text-align: center; width: 100%"> </td></tr></tbody></table>',
        convert_to_text=False,
    ) == ("<html><head></head><body></body></html>")


def test_a_table_of_only_whitespace_cells_is_omitted_in_fallback_mode() -> None:
    result = convert_html_tables_to_ascii(
        "<html><body><table><tr><td>   </td><td>\n</td></tr></table></body></html>",
        convert_to_text=False,
    )
    assert "<TABLE>" not in result


def test_a_nonempty_table_keeps_its_canonical_label_in_fallback_mode() -> None:
    result = convert_html_tables_to_ascii(
        "<html><body><table><tr><th>Item</th></tr><tr><td>Value</td></tr></table></body></html>",
        convert_to_text=False,
    )
    assert "<TABLE>" in result
    assert "Item" in result
    assert "Value" in result


def test_a_table_whose_nested_cell_carries_text_is_preserved() -> None:
    result = convert_html_tables_to_ascii(
        "<html><body><table><tr><td>Outer text</td>"
        "<td><table><tr><td>Nested</td></tr></table></td></tr></table></body></html>",
        convert_to_text=False,
    )
    assert "<TABLE>" in result
    assert "Outer text" in result


def test_an_empty_table_among_real_tables_is_omitted_from_the_rendered_list() -> None:
    result = convert_html_tables_to_ascii(
        "<html><body><table><tr><td> </td></tr></table>"
        "<table><tr><td>Real</td></tr></table></body></html>",
        convert_to_text=False,
    )
    assert result.count("<TABLE>") == 1
    assert "Real" in result


def test_geometry_reports_the_logical_rows_rather_than_the_rendered_lines() -> None:
    _text, geometries = convert_html_tables_to_ascii_with_metadata(
        "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>", convert_to_text=False
    )
    assert geometries[0].rows == (("A",), ("1",))


def test_geometry_reports_its_documented_field_types() -> None:
    _text, geometries = convert_html_tables_to_ascii_with_metadata(
        "<table><tr><th>Metric</th><th>Value</th></tr>"
        "<tr><td>Sales</td><td>5</td></tr></table>"
    )
    geometry = geometries[0]
    assert isinstance(geometry.table_index, int)
    assert isinstance(geometry.rows, tuple)
    assert isinstance(geometry.column_alignments, tuple)
    assert isinstance(geometry.column_widths, tuple)
    assert isinstance(geometry.header_row_count, int)
    assert isinstance(geometry.span_groups, tuple)
    assert isinstance(geometry.confidence, float)
    assert isinstance(geometry.diagnostics, tuple)
    assert isinstance(geometry.is_fallback_to_legacy, bool)


def test_conversion_accepts_bytes_and_a_preparsed_node() -> None:
    from edgar_sec.engine.document.html.tree import parse_html

    html = b"<table><tr><td>a</td></tr></table>"
    assert convert_html_table(html).ascii_text.startswith("<TABLE>")
    node = parse_html("<table><tr><td>a</td></tr></table>").css_first("table")
    assert node is not None
    assert convert_html_table(node).ascii_text.startswith("<TABLE>")


def test_early_unwrap_of_false_tables_produces_no_canonical_label() -> None:
    text, geometries = convert_html_tables_to_ascii_with_metadata(
        "<table><tr><td>1. first prose row</td><td>alpha</td></tr>"
        "<tr><td>2. second prose row</td><td>beta</td></tr></table>",
        early_unwrap_false_tables=True,
    )
    assert "<TABLE>" not in text
    assert geometries == ()
    assert "first prose row" in text


def test_without_early_unwrap_the_same_layout_table_is_rendered() -> None:
    text, _geometries = convert_html_tables_to_ascii_with_metadata(
        "<table><tr><td>1. first prose row</td><td>alpha</td></tr>"
        "<tr><td>2. second prose row</td><td>beta</td></tr></table>"
    )
    assert "<TABLE>" in text


def test_a_continuation_across_a_page_break_becomes_one_table() -> None:
    header = "<tr><th>Item</th><th>2017</th><th>2018</th></tr>"
    result = convert_html_tables_to_ascii(
        "<table>"
        + header
        + "<tr><td>Revenue</td><td>1,000</td><td>1,200</td></tr></table>"
        "<table>"
        + header
        + "<tr><td>Expenses</td><td>400</td><td>450</td></tr></table>"
    )
    assert result.count("<TABLE>") == 1
    assert "Revenue" in result
    assert "Expenses" in result


def test_render_grid_to_ascii_emits_a_canonical_block_from_plain_text() -> None:
    text = render_grid_to_ascii([["Item", "Amount"], ["Revenue", "1,200"]])
    assert text.startswith("<TABLE>")
    assert text.endswith("</TABLE>")
    assert "Revenue" in text
    assert "---" in text


def test_render_grid_to_ascii_of_an_empty_matrix_is_empty() -> None:
    assert render_grid_to_ascii([]) == ""
    assert render_grid_to_ascii([[]]) == ""


@pytest.mark.parametrize("convert_to_text", [True, False])
def test_both_modes_agree_on_whether_a_table_survives(convert_to_text: bool) -> None:
    text = convert_html_tables_to_ascii(
        "<table><tr><td> </td></tr></table><table><tr><td>Real</td></tr></table>",
        convert_to_text=convert_to_text,
    )
    assert text.count("<TABLE>") == 1
