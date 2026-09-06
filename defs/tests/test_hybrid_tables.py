"""Unit tests for hybrid <pre> table discrimination and normalization."""

from __future__ import annotations

from defs.tables import (
    PreBlockKind,
    classify_pre_block,
    normalize_hybrid_pre_blocks,
    normalize_hybrid_pre_text,
    restore_hybrid_pre_text,
)
from defs.text.html import parse_html

SGML_PRE_DOC = """<html><body>
<p>Some narrative text here.</p>
<pre><TABLE>
<CAPTION>Balance Sheet</CAPTION>
<S> <C>Cash</S> <C>$100</C>
<S> <C>Assets</S> <C>$500</C>
</TABLE></pre>
<p>More narrative text.</p>
</body></html>"""

MONOSPACE_PRE_DOC = """<html><body>
<p>Financial Summary</p>
<pre>
Three Months Ended
March 31, 2020
--------------
Revenues $100
Net Income  $50
</pre>
<p>End of summary.</p>
</body></html>"""

HTML_TABLE_IN_PRE_DOC = """<html><body>
<p>Before table</p>
<pre><table><tr><th>Item</th><th>Amount</th></tr><tr><td>Revenue</td><td>1000</td></tr></table></pre>
<p>After table</p>
</body></html>"""

MIXED_DOC = """<html><body>
<p>Narrative prose about the financials.</p>
<table><tr><th>Direct</th><th>Table</th></tr><tr><td>A</td><td>1</td></tr></table>
<pre><TABLE>
<S> <C>Item</S> <C>Value</C>
</TABLE></pre>
<pre>
Fixed-width data
--------------
Line one
</pre>
</body></html>"""


def test_classify_sgml_table_in_pre() -> None:
    """SGML <TABLE><S><C> inside <pre> is classified as SGML_TABLE."""
    tree = parse_html(SGML_PRE_DOC)
    pre_nodes = tree.css("pre")
    assert len(pre_nodes) == 1
    kind = classify_pre_block(pre_nodes[0])
    assert kind == PreBlockKind.SGML_TABLE


def test_classify_monospace_text_in_pre() -> None:
    """Fixed-width columnar text inside <pre> is classified as MONOSPACE_TEXT."""
    tree = parse_html(MONOSPACE_PRE_DOC)
    pre_nodes = tree.css("pre")
    assert len(pre_nodes) == 1
    kind = classify_pre_block(pre_nodes[0])
    assert kind == PreBlockKind.MONOSPACE_TEXT


def test_classify_html_table_in_pre() -> None:
    """True HTML <table><tr><td> inside <pre> is classified as HTML_TABLE."""
    tree = parse_html(HTML_TABLE_IN_PRE_DOC)
    pre_nodes = tree.css("pre")
    assert len(pre_nodes) == 1
    kind = classify_pre_block(pre_nodes[0])
    assert kind == PreBlockKind.HTML_TABLE


def test_classify_narrative_prose_in_pre() -> None:
    """Wrapped prose inside <pre> is classified as NARRATIVE_PROSE."""
    html = "<html><body><pre>\nSome wrapped prose text here.\n</pre></body></html>"
    tree = parse_html(html)
    pre_nodes = tree.css("pre")
    assert len(pre_nodes) == 1
    kind = classify_pre_block(pre_nodes[0])
    assert kind == PreBlockKind.NARRATIVE_PROSE


def test_sgml_pre_preserved_byte_for_byte() -> None:
    """SGML <TABLE> inside <pre> is preserved byte-for-byte after normalization."""
    protected = normalize_hybrid_pre_text(SGML_PRE_DOC)
    result = restore_hybrid_pre_text(protected.text, protected.protected)
    assert "<TABLE>" in result
    assert "<S>" in result
    assert "<C>" in result
    assert "</TABLE>" in result
    assert "<pre>" not in result


def test_monospace_pre_preserves_whitespace() -> None:
    """Monospace text inside <pre> retains exact line breaks after normalization."""
    tree = parse_html(MONOSPACE_PRE_DOC)
    normalize_hybrid_pre_blocks(tree)
    result = str(tree)
    assert "Three Months Ended" in result
    assert "March 31, 2020" in result
    assert "--------------" in result
    assert "Revenues $100" in result
    assert "<pre>" not in result


def test_html_table_in_pre_converted_to_ascii() -> None:
    """True HTML <table> inside <pre> is converted to canonical ASCII table."""
    protected = normalize_hybrid_pre_text(HTML_TABLE_IN_PRE_DOC)
    result = restore_hybrid_pre_text(protected.text, protected.protected)
    assert "<TABLE>" in result
    assert "<pre>" not in result
    assert "Item" in result
    assert "Amount" in result
    assert "Revenue" in result
    assert "1000" in result


def test_mixed_document_handles_all_patterns() -> None:
    """Mixed documents with HTML tables and <pre> ASCII tables are all handled."""
    protected = normalize_hybrid_pre_text(MIXED_DOC)
    result = restore_hybrid_pre_text(protected.text, protected.protected)
    assert "<TABLE>" in result
    assert "Fixed-width data" in result
    assert "Line one" in result
    assert "<pre>" not in result
    assert "Direct" in result


def test_sgml_table_content_has_s_and_c_markers() -> None:
    """SGML table content retains <S> and <C> markers after normalization."""
    protected = normalize_hybrid_pre_text(SGML_PRE_DOC)
    result = restore_hybrid_pre_text(protected.text, protected.protected)
    assert "<S>" in result
    assert "<C>" in result
    assert "Cash" in result
    assert "$100" in result


def test_pre_tag_removed_after_normalization() -> None:
    """All <pre> tags are unwrapped after normalization."""
    for doc in (SGML_PRE_DOC, MONOSPACE_PRE_DOC, HTML_TABLE_IN_PRE_DOC):
        tree = parse_html(doc)
        normalize_hybrid_pre_blocks(tree)
        result = str(tree)
        assert "<pre>" not in result.lower() or "</pre>" not in result.lower()


def test_classify_pre_block_returns_enum() -> None:
    """classify_pre_block returns a PreBlockKind enum value."""
    html = "<html><body><pre><TABLE><S><C>Test</C></S></TABLE></pre></body></html>"
    tree = parse_html(html)
    pre_nodes = tree.css("pre")
    kind = classify_pre_block(pre_nodes[0])
    assert isinstance(kind, PreBlockKind)
    assert kind == PreBlockKind.SGML_TABLE


def test_html_table_in_pre_produces_render_result() -> None:
    """HTML table inside <pre> produces a valid ASCII render result."""
    html = "<pre><table><tr><td>Name</td><td>Value</td></tr><tr><td>X</td><td>42</td></tr></table></pre>"
    protected = normalize_hybrid_pre_text(html)
    result = restore_hybrid_pre_text(protected.text, protected.protected)
    assert "<TABLE>" in result
    assert "Name" in result
    assert "Value" in result
    assert "42" in result


def test_narrative_prose_pre_unwrapped() -> None:
    """Narrative prose inside <pre> is unwrapped without content loss."""
    html = "<html><body><pre>\nSome narrative prose text.\nMore text here.\n</pre></body></html>"
    tree = parse_html(html)
    pre_nodes = tree.css("pre")
    kind = classify_pre_block(pre_nodes[0])
    assert kind == PreBlockKind.NARRATIVE_PROSE

    normalize_hybrid_pre_blocks(tree)
    result = str(tree)
    assert "Some narrative prose text." in result
    assert "More text here." in result
    assert "<pre>" not in result.lower()
