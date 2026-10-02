"""Unit tests for page-break sentinel injection outside table spans.

The table exclusion is the whole point of this module. A break tag inside a
table is page *furniture* — a decorative rule, a column underline — and
converting it to a sentinel makes the ASCII table renderer wrap that sentinel
as cell text, corrupting both the table and the page structure. These tests pin
that the exclusion holds, not merely that sentinels are produced.
"""

from __future__ import annotations

from edgar_sec.engine.document.html.breaks import (
    PAGE_BREAK_HINT_TOKENS,
    PAGE_MARKER_LINE,
    PAGE_SPLIT_SENTINEL,
    collapse_marker_runs,
    insert_page_sentinels,
    render_html_to_break_text,
)

TAGGED_TABLE = (
    "<TABLE><TR><TD>Item</TD><TD>Amount</TD></TR>\n"
    "<TR><TD>Widgets</TD><TD>$1,000</TD></TR></TABLE>"
)


def test_insert_page_sentinels_converts_hr_and_css_breaks() -> None:
    html = """
    <div>Page 1 content</div>
    <hr>
    <div style="page-break-before: always">Page 2 content</div>
    <div class="pagebreak">Page 3 content</div>
    """
    result = insert_page_sentinels(html)
    assert PAGE_SPLIT_SENTINEL in result
    assert result.count(PAGE_SPLIT_SENTINEL) == 3


def test_insert_page_sentinels_ignores_hr_inside_tables() -> None:
    html = """
    <div>Outside before</div>
    <hr>
    <TABLE>
        <TR><TD><hr></TD></TR>
    </TABLE>
    <hr>
    <div>Outside after</div>
    """
    result = insert_page_sentinels(html)
    assert result.count(PAGE_SPLIT_SENTINEL) == 2
    assert "<TABLE>" in result
    assert "<hr>" in result


def test_insert_page_sentinels_preserves_table_bytes_exactly() -> None:
    html = f"prose\n{TAGGED_TABLE}\nmore prose"
    result = insert_page_sentinels(html)
    assert TAGGED_TABLE in result


def test_insert_page_sentinels_handles_breaks_before_and_after_a_table() -> None:
    html = f"<hr>before{TAGGED_TABLE}<hr>after"
    result = insert_page_sentinels(html)
    assert result.count(PAGE_SPLIT_SENTINEL) == 2
    assert TAGGED_TABLE in result


def test_insert_page_sentinels_leaves_non_breaking_rules_alone() -> None:
    html = "<div style='page-break-inside:avoid'>x</div>"
    assert insert_page_sentinels(html) == html


def test_insert_page_sentinels_recognizes_dss_page_tags() -> None:
    result = insert_page_sentinels("<page>marker</page>")
    assert PAGE_SPLIT_SENTINEL in result
    assert "<page>" not in result


def test_insert_page_sentinels_on_text_without_breaks_is_a_noop() -> None:
    html = "<p>plain paragraph</p>"
    assert insert_page_sentinels(html) == html


def test_insert_page_sentinels_on_empty_input() -> None:
    assert insert_page_sentinels("") == ""


def test_class_and_id_hint_tokens_are_matched() -> None:
    for token in PAGE_BREAK_HINT_TOKENS[:4]:
        result = insert_page_sentinels(f'<div class="{token}">x</div>')
        assert PAGE_SPLIT_SENTINEL in result


def test_unrelated_class_names_are_not_break_hints() -> None:
    html = '<div class="page-number">x</div>'
    assert insert_page_sentinels(html) == html


def test_collapse_marker_runs_removes_padding_around_a_run() -> None:
    """Blank lines and trailing space around markers are normalized away."""
    collapsed = collapse_marker_runs(f"First\n  {PAGE_MARKER_LINE}  \n\n  Second")
    assert collapsed == f"First\n{PAGE_MARKER_LINE}\nSecond"


def test_collapse_marker_runs_keeps_repeated_markers() -> None:
    """Two breaks in a row are evidence of a blank page, not a duplicate."""
    collapsed = collapse_marker_runs(
        f"First\n{PAGE_MARKER_LINE}\n{PAGE_MARKER_LINE}\nSecond"
    )
    assert collapsed.count(PAGE_MARKER_LINE) == 2


def test_collapse_marker_runs_on_text_without_markers() -> None:
    text = "First\nSecond"
    assert collapse_marker_runs(text) == text


def test_sentinel_token_avoids_glyph_mapped_letters() -> None:
    """Stage 1 maps r/R to checkbox glyphs inside symbolic-font scopes."""
    assert "SPLIT" in PAGE_SPLIT_SENTINEL
    assert "r" not in PAGE_SPLIT_SENTINEL.lower()


def test_marker_line_is_not_the_artifact_token() -> None:
    """`[[SEC:PAGE_BREAK id=N]]` is produced at the artifact boundary, not here."""
    assert PAGE_MARKER_LINE == "<PAGE>"
    assert "SEC:PAGE_BREAK" not in PAGE_MARKER_LINE


def test_render_html_to_break_text_carries_page_boundaries() -> None:
    html = (
        "<html><body><p>Page one.</p>"
        '<div style="page-break-before:always">Page two.</div>'
        "</body></html>"
    )
    result = render_html_to_break_text(html)
    assert PAGE_MARKER_LINE in result
    assert "Page one." in result
    assert "Page two." in result
    assert PAGE_SPLIT_SENTINEL not in result


def test_render_html_to_break_text_preserves_table_geometry() -> None:
    html = (
        "<html><body><p>Intro.</p>"
        '<table border="1"><tr><th>A</th><th>B</th></tr>'
        "<tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></table>"
        "</body></html>"
    )
    result = render_html_to_break_text(html)
    assert "<TABLE>" in result
    assert len(result.table_geometries) == 1


def test_render_html_to_break_text_on_empty_input() -> None:
    result = render_html_to_break_text("")
    assert str(result) == ""
    assert result.table_geometries == ()


def test_render_html_to_break_text_keeps_table_bytes_across_a_break() -> None:
    html = (
        "<html><body>"
        '<table border="1"><tr><th>A</th><th>B</th></tr>'
        "<tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr>"
        "<tr><td>5</td><td>6</td></tr></table><hr>"
        "</body></html>"
    )
    result = render_html_to_break_text(html)
    assert "<TABLE>" in result
    assert PAGE_MARKER_LINE in result
