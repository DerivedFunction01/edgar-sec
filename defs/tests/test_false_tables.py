"""Tests for the false/layout table unwrap pass."""

from __future__ import annotations

from defs.tables import cleanup_false_tables
from defs.tables.false_tables import is_false_table
from defs.text.html import normalize_html_document


def test_single_cell_bullet_is_unwrapped() -> None:
    text = "<TABLE>\n• our restaurant concept;\n</TABLE>"

    assert is_false_table(text) is True
    assert cleanup_false_tables(text) == "• our restaurant concept;"


def test_consecutive_single_cell_bullets_stay_on_separate_lines() -> None:
    text = (
        "<TABLE>\n• one bullet;\n</TABLE> "
        "<TABLE>\n• two bullets;\n</TABLE> "
        "<TABLE>\n• three bullets;\n</TABLE>"
    )

    result = cleanup_false_tables(text)

    assert result == "• one bullet;\n• two bullets;\n• three bullets;"


def test_lettered_list_items_stay_on_separate_lines() -> None:
    text = "<TABLE>\n(a) first item;\n</TABLE> <TABLE>\n(b) second item;\n</TABLE>"

    result = cleanup_false_tables(text)

    assert result == "(a) first item;\n(b) second item;"


def test_consecutive_prose_fragments_collapse_with_spaces() -> None:
    text = "<TABLE>\nFirst fragment.\n</TABLE> <TABLE>\nSecond fragment.\n</TABLE>"

    result = cleanup_false_tables(text)

    assert result == "First fragment. Second fragment."


def test_item_heading_table_is_retained() -> None:
    text = "<TABLE>\nITEM 5. MARKET FOR REGISTRANT'S COMMON EQUITY\n</TABLE>"

    assert is_false_table(text) is False
    assert cleanup_false_tables(text) == text


def test_part_heading_table_is_retained() -> None:
    text = "<TABLE>\nPART I\n</TABLE>"

    assert is_false_table(text) is False
    assert cleanup_false_tables(text) == text


def test_multi_line_financial_table_is_retained() -> None:
    text = (
        "<TABLE>\n"
        "Cash and cash equivalents    $ 29,224 $ 24,335\n"
        "----------------------  --------------- ------------\n"
        "Net working capital        $ (71,938) $ (62,212)\n"
        "</TABLE>"
    )

    assert is_false_table(text) is False
    assert cleanup_false_tables(text) == text


def test_empty_table_is_not_classified_as_false() -> None:
    text = "<TABLE>\n</TABLE>"

    assert is_false_table(text) is False
    assert cleanup_false_tables(text) == text


def test_pipeline_unwraps_consecutive_bullets_and_keeps_others() -> None:
    html = (
        "<html><body>"
        "Before "
        "<TABLE><TR><TD>• first bullet;</TD></TR></TABLE> "
        "<TABLE><TR><TD>• second bullet;</TD></TR></TABLE> "
        "<TABLE><TR><TD>ITEM 5. HEADING</TD></TR></TABLE> "
        "<table><tr><th>2018</th><th>2017</th></tr>"
        "<tr><td>Cash</td><td>$ 29</td><td>$ 24</td></tr>"
        "<tr><td>---</td><td>---</td><td>---</td></tr>"
        "<tr><td>Equity</td><td>$ 100</td><td>$ 90</td></tr>"
        "</table>"
        " After"
        "</body></html>"
    )

    result = normalize_html_document(html)

    assert "• first bullet;" in result
    assert "• second bullet;" in result
    assert "ITEM 5. HEADING" in result
    assert "$ 29" in result
    assert "$ 100" in result
    assert "After" in result
