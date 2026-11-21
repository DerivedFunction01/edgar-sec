"""Pins for the direct-cells home (Wave 2B).
The row-cell walk lives in ``index_pages.parser``;
``parser_browse`` binds it.
"""

from __future__ import annotations

from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.engine.index_pages import parser, parser_browse


def test_binding_is_the_parser_home() -> None:
    assert parser_browse._direct_cells is parser._direct_cells


def test_direct_cells_verdicts() -> None:
    tree = parse_html("<table><tr><td>a</td><th>b</th><td>c</td></tr></table>")
    rows = tree.css("tr")
    assert len(rows) == 1
    cells = parser._direct_cells(rows[0])
    assert [cell.tag for cell in cells] == ["td", "th", "td"]
