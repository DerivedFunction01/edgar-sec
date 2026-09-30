"""Unit tests for HTML page-break sentinel injection outside table spans."""

from __future__ import annotations

from edgar_sec.engine.document.html_breaks import (
    PAGE_SENTINEL,
    convert_sentinels_to_page_markers,
    insert_page_sentinels,
)


def test_insert_page_sentinels_converts_hr_and_css_breaks() -> None:
    html = """
    <div>Page 1 content</div>
    <hr>
    <div style="page-break-before: always">Page 2 content</div>
    <div class="pagebreak">Page 3 content</div>
    """
    res = insert_page_sentinels(html)
    assert PAGE_SENTINEL in res
    assert res.count(PAGE_SENTINEL) == 3


def test_insert_page_sentinels_ignores_hr_inside_tables() -> None:
    html = """
    <div>Outside before</div>
    <hr>
    <table>
        <tr><td>Cell 1</td></tr>
        <tr><td><hr></td></tr>
        <tr><td>Cell 2</td></tr>
    </table>
    <hr>
    <div>Outside after</div>
    """
    res = insert_page_sentinels(html)
    # The two outside <hr> should be converted; the one inside <table> should remain <hr>
    assert res.count(PAGE_SENTINEL) == 2
    assert "<table>" in res
    assert "<hr>" in res


def test_convert_sentinels_to_page_markers() -> None:
    text = f"First page\n{PAGE_SENTINEL}\n\nSecond page\n{PAGE_SENTINEL}\nThird page"
    converted = convert_sentinels_to_page_markers(text)
    assert "<PAGE>" in converted
    assert PAGE_SENTINEL not in converted
    lines = converted.split("\n")
    assert any(line.strip() == "<PAGE>" for line in lines)
