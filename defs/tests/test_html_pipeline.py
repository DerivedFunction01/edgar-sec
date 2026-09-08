from __future__ import annotations

from defs.tables.ascii_html import TableGeometry
from defs.tables.ascii_html.model import HorizontalAlign
from defs.text.html import NormalizedHtmlText, normalize_html_document


def test_normalize_html_document_preserves_paragraph_unity() -> None:
    html = "<p>This is a <span>single</span> paragraph.</p>"

    assert normalize_html_document(html) == "This is a single paragraph."


def test_normalize_html_document_keeps_false_table_stage_explicit() -> None:
    calls: list[str] = []

    def cleanup(text: str) -> str:
        calls.append(text)
        return text

    assert normalize_html_document("<p>One</p><p>Two</p>", cleanup_tables=cleanup) == (
        "One\n\nTwo"
    )
    assert calls == ["<html><head></head><body><p>One</p><p>Two</p></body></html>"]


def test_normalize_html_document_preserves_rendered_table_tags() -> None:
    html = "<table><tr><th>Metric</th><th>Value</th></tr><tr><td>Sales</td><td>5</td></tr></table>"

    normalized = normalize_html_document(html)

    assert normalized.startswith("<TABLE>\n")
    assert normalized.endswith("\n</TABLE>")
    assert "Metric" in normalized
    assert "Sales" in normalized


def test_normalize_html_document_preserves_literal_sgml_table_in_pre() -> None:
    html = "<html><body><pre><TABLE>\n<S>Revenue <C>100\n</TABLE></pre></body></html>"

    normalized = normalize_html_document(html)

    assert normalized == "<TABLE>\n<S>Revenue <C>100\n</TABLE>"


def test_normalize_html_document_renders_html_table_in_pre() -> None:
    html = "<html><body><pre><table><tr><td>Revenue</td><td>100</td></tr></table></pre></body></html>"

    normalized = normalize_html_document(html)

    assert normalized.startswith("<TABLE>\n")
    assert "Revenue" in normalized
    assert "100" in normalized


def test_normalize_html_document_returns_normalized_html_text() -> None:
    """normalize_html_document returns text with HTML geometry metadata."""
    html = "<p>Hello</p>"
    result = normalize_html_document(html)
    assert isinstance(result, NormalizedHtmlText)
    assert isinstance(result, str)
    assert result == "Hello"


def test_normalize_html_document_retains_table_geometries() -> None:
    """Per-table geometry metadata is retained after normalization."""
    html = (
        "<table><tr><th>Metric</th><th>Value</th></tr>"
        "<tr><td>Sales</td><td>5</td></tr></table>"
    )
    result = normalize_html_document(html)
    assert isinstance(result, NormalizedHtmlText)
    assert len(result.table_geometries) == 1
    geom = result.table_geometries[0]
    assert isinstance(geom, TableGeometry)
    assert geom.table_index == 0
    assert len(geom.rows) == 2
    assert geom.header_row_count == 1
    assert isinstance(geom.confidence, float)
    assert isinstance(geom.diagnostics, tuple)
    assert isinstance(geom.is_fallback_to_legacy, bool)


def test_normalize_html_document_geometry_retains_row_and_cell_geometry() -> None:
    """TableGeometry rows, alignments, and widths are populated."""
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    result = normalize_html_document(html)
    geom = result.table_geometries[0]
    assert len(geom.rows) == 2
    assert geom.rows[0] == ("A", "B")
    assert geom.rows[1] == ("1", "2")
    assert len(geom.column_alignments) == 2
    assert len(geom.column_widths) == 2
    assert all(isinstance(a, HorizontalAlign) for a in geom.column_alignments)
    assert all(isinstance(w, int) for w in geom.column_widths)


def test_normalize_html_document_empty_geometry_for_no_tables() -> None:
    """No tables means empty geometry tuple."""
    html = "<p>No tables here</p>"
    result = normalize_html_document(html)
    assert result.table_geometries == ()


def test_normalize_html_document_empty_table_omitted_from_metadata() -> None:
    """Wholly-empty tables produce no geometry metadata."""
    html = "<html><body><table><tr><td> </td></tr></table></body></html>"
    result = normalize_html_document(html)
    assert result.table_geometries == ()


def test_normalize_html_document_false_table_drops_geometry() -> None:
    result = normalize_html_document("<table><tr><td>One layout row</td></tr></table>")

    assert result == "One layout row"
    assert result.table_geometries == ()


def test_normalize_html_document_string_compatibility() -> None:
    """NormalizedHtmlText supports ordinary string operations."""
    html = (
        "<table><tr><th>Item</th><th>Amount</th></tr>"
        "<tr><td>Cash</td><td>100</td></tr></table>"
    )
    result = normalize_html_document(html)
    assert result.startswith("<TABLE>")
    assert result.endswith("</TABLE>")
    assert "Item" in result
    assert "Cash" in result
    assert len(result) > 0


def test_normalize_html_document_multiple_tables_multiple_geometries() -> None:
    """Multiple tables produce multiple geometry entries."""
    html = (
        "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
        "<table><tr><th>B</th></tr><tr><td>2</td></tr></table>"
    )
    result = normalize_html_document(html)
    assert len(result.table_geometries) == 2
    assert result.table_geometries[0].table_index == 0
    assert result.table_geometries[1].table_index == 1


def test_normalize_html_document_cleanup_false_tables_stage_ordering() -> None:
    """cleanup_false_tables still runs after table rendering."""
    calls: list[str] = []

    def cleanup(text: str) -> str:
        calls.append(text)
        return text

    html = "<table><tr><th>X</th></tr><tr><td>Y</td></tr></table>"
    normalize_html_document(html, cleanup_tables=cleanup)
    assert len(calls) >= 1
    assert "<TABLE>" in calls[-1]


def test_normalize_html_document_empty_string_returns_empty_normalized() -> None:
    """Empty HTML returns empty text and no geometries."""
    result = normalize_html_document("")
    assert result == ""
    assert result.table_geometries == ()


def test_normalize_html_document_geometry_span_groups_present() -> None:
    """TableGeometry includes span_groups from ResolvedGrid."""
    html = (
        '<table><tr><th colspan="2">Title</th></tr>'
        "<tr><td>A</td><td>B</td></tr></table>"
    )
    result = normalize_html_document(html)
    geom = result.table_geometries[0]
    assert isinstance(geom.span_groups, tuple)
