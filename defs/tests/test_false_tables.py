"""Tests for the false/layout table unwrap pass."""

from __future__ import annotations

from defs.tables import (
    TableGeometry,
    cleanup_false_tables,
    cleanup_false_tables_with_metadata,
    convert_html_table,
)
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


def test_geometry_rows_drive_false_table_classification() -> None:
    result = convert_html_table("<table><tr><td>One logical row</td></tr></table>")
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>One logical row\nwrapped display line</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == "One logical row"


def test_geometry_unwraps_multiline_single_column_prose() -> None:
    result = convert_html_table(
        "<table><tr><td>This is a long prose fragment</td></tr>"
        "<tr><td>continued in a second logical row</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered wrapped lines</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == (
        "This is a long prose fragment continued in a second logical row"
    )


def test_geometry_unwraps_bullet_and_prose_columns() -> None:
    result = convert_html_table(
        "<table><tr><td>•</td><td>This is a prose bullet item</td></tr>"
        "<tr><td>•</td><td>Another prose bullet item</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered wrapped lines</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == (
        "• This is a prose bullet item\n• Another prose bullet item"
    )


def test_geometry_retains_simple_numeric_two_column_table() -> None:
    result = convert_html_table(
        "<table><tr><td>Revenue</td><td>100</td></tr>"
        "<tr><td>Expenses</td><td>50</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered financial rows</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == text


def test_geometry_retains_numeric_exhibit_index_marker() -> None:
    result = convert_html_table(
        "<table><tr><td>1</td><td>Material Contract</td></tr>"
        "<tr><td>2</td><td>Lease Agreement</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered exhibit rows</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == text


def test_geometry_unwraps_numeric_footnote_prose_rows() -> None:
    prose = (
        "Previously filed in S-1 Registration Statement No. 230682 filed with the "
        "Commission on November 7, 1968 and amended twice."
    )
    result = convert_html_table(
        f"<table><tr><td>(1)</td><td>{prose}</td></tr>"
        f"<tr><td>(2)</td><td>Previously filed as an exhibit to the Company's Form 10-K filed in 1971.</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered footnote rows</TABLE>"

    assert (
        cleanup_false_tables(text, (geometry,))
        == f"(1) {prose}\n(2) Previously filed as an exhibit to the Company's Form 10-K filed in 1971."
    )


def test_geometry_unwraps_paren_numbered_rows_without_punctuation() -> None:
    result = convert_html_table(
        "<table><tr><td>(1)</td><td>First list item without terminal punctuation</td></tr>"
        "<tr><td>(2)</td><td>Second list item without terminal punctuation</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered wrapped lines</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == (
        "(1) First list item without terminal punctuation\n"
        "(2) Second list item without terminal punctuation"
    )


def test_geometry_unwraps_three_column_paren_ordered_grid() -> None:
    result = convert_html_table(
        "<table><tr><td>(1)</td><td>Incorporated by reference to</td><td>Form 10-K</td></tr>"
        "<tr><td>(2)</td><td>Incorporated by reference to</td><td>Form 10-Q</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered incorporation rows</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == (
        "(1) Incorporated by reference to Form 10-K\n"
        "(2) Incorporated by reference to Form 10-Q"
    )


def test_geometry_unwraps_paren_roman_prose_rows() -> None:
    result = convert_html_table(
        "<table><tr><td>(i)</td><td>The first enumerated footnote with several words</td></tr>"
        "<tr><td>(ii)</td><td>The second enumerated footnote with several words</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered roman rows</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == (
        "(i) The first enumerated footnote with several words\n"
        "(ii) The second enumerated footnote with several words"
    )


def test_geometry_retains_paren_marker_rows_with_numeric_second_column() -> None:
    result = convert_html_table(
        "<table><tr><td>(123)</td><td>924,643</td></tr>"
        "<tr><td>(456)</td><td>876,348</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered financial rows</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == text


def test_geometry_retains_footnote_table_with_short_label_row() -> None:
    result = convert_html_table(
        "<table><tr><td>(1)</td><td>End of year statistics.</td></tr>"
        "<tr><td>(2)</td><td>Digital rooms are equipped with an interactive digital "
        "system where on-demand movies are stored in a digital format</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered footnote rows</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == text


def test_geometry_ignores_empty_spacer_columns_and_rows() -> None:
    prose = (
        "Incident Response and Recovery Planning: BlackRock has established and "
        "maintains incident response and recovery plans that address response "
        "obligations and mitigate potential reputational damage."
    )
    result = convert_html_table(
        f"<table><tr><td></td><td>\u25cf</td><td>{prose}</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered spacer rows</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == f"\u25cf {prose}"


def test_geometry_unwraps_footnote_rows_with_empty_spacer_row() -> None:
    prose = (
        "Percentage based on 54,000,000 shares of common stock outstanding on "
        "December 31, 2013"
    )
    result = convert_html_table(
        f"<table><tr><td>(1)</td><td>{prose}</td></tr>"
        "<tr><td></td><td></td></tr>"
        f"<tr><td>(2)</td><td>Cede & Co. acting as a depository service for beneficial holders holds shares.</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered percentage footnotes</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == (
        f"(1) {prose}\n(2) Cede & Co. acting as a depository service for "
        "beneficial holders holds shares."
    )


def test_geometry_unwraps_spacer_column_lettered_footnote() -> None:
    result = convert_html_table(
        "<table><tr><td></td><td>(a)</td>"
        "<td>is not liable pursuant to Nevada Revised Statute 78.138, or</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered lettered footnote</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == (
        "(a) is not liable pursuant to Nevada Revised Statute 78.138, or"
    )


def test_footnote_preceding_retained_table_unwraps_label_text() -> None:
    result = convert_html_table(
        "<table><tr><td>(1)</td><td>Percent of class</td></tr></table>"
    )
    footnote_geometry = TableGeometry(table_index=0, render_result=result)
    retained = convert_html_table(
        "<table><tr><td>Owner</td><td>Shares</td></tr>"
        "<tr><td>Officers</td><td>100</td></tr></table>"
    )
    retained_geometry = TableGeometry(table_index=1, render_result=retained)

    footnote_table = "<TABLE>(1) rendered footnote</TABLE>"
    retained_table = "<TABLE>rendered ownership table</TABLE>"
    text = f"{footnote_table}\n{retained_table}"

    assert cleanup_false_tables(text, (footnote_geometry, retained_geometry)) == (
        "(1) Percent of class\n" + retained_table
    )


def test_footnote_without_following_table_stays_retained() -> None:
    result = convert_html_table(
        "<table><tr><td>(1)</td><td>Percent of class</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>(1) rendered footnote</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == text


def test_geometry_unwraps_monotonic_ordered_prose_rows() -> None:
    result = convert_html_table(
        "<table><tr><td>1)</td><td>This is the first long prose item in the list.</td></tr>"
        "<tr><td>2)</td><td>This is the second long prose item in the list.</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered ordered rows</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == (
        "1) This is the first long prose item in the list.\n"
        "2) This is the second long prose item in the list."
    )


def test_geometry_unwraps_ordered_prose_across_spacer_columns() -> None:
    result = convert_html_table(
        "<table><tr><td>1)</td><td></td><td>This is the first long prose item in the list.</td></tr>"
        "<tr><td></td><td>i)</td><td>This is the nested long prose item in the list.</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered nested ordered rows</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == (
        "1) This is the first long prose item in the list.\n"
        "i) This is the nested long prose item in the list."
    )


def test_geometry_unwraps_single_column_prose_rows() -> None:
    result = convert_html_table(
        "<table><tr><td>Level 1 \u2013 Unadjusted quoted prices in active markets for identical assets or liabilities.</td></tr>"
        "<tr><td>Level 2 \u2013 Inputs other than quoted prices included within Level 1 that are observable for the asset or liability.</td></tr>"
        "<tr><td>Level 3 \u2013 Unobservable inputs used in determining the fair value of investments.</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered level rows</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == (
        "Level 1 \u2013 Unadjusted quoted prices in active markets for identical assets or liabilities.\n"
        "Level 2 \u2013 Inputs other than quoted prices included within Level 1 that are observable for the asset or liability.\n"
        "Level 3 \u2013 Unobservable inputs used in determining the fair value of investments."
    )


def test_geometry_retains_single_column_numeric_rows() -> None:
    result = convert_html_table(
        "<table><tr><td>2023</td></tr><tr><td>2024</td></tr><tr><td>1,000</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered numeric rows</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == text


def test_geometry_unwraps_single_numeric_cell() -> None:
    result = convert_html_table("<table><tr><td>$5,000</td></tr></table>")
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered single value</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == "$5,000"


def test_geometry_letter_sequence_keeps_roman_ambiguous_letters() -> None:
    result = convert_html_table(
        "<table><tr><td>g)</td><td>This is the seventh long prose item in the list.</td></tr>"
        "<tr><td>h)</td><td>This is the eighth long prose item in the list.</td></tr>"
        "<tr><td>i)</td><td>This is the ninth long prose item in the list.</td></tr>"
        "<tr><td>j)</td><td>This is the tenth long prose item in the list.</td></tr>"
        "<tr><td>k)</td><td>This is the eleventh long prose item in the list.</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered letter rows</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == (
        "g) This is the seventh long prose item in the list.\n"
        "h) This is the eighth long prose item in the list.\n"
        "i) This is the ninth long prose item in the list.\n"
        "j) This is the tenth long prose item in the list.\n"
        "k) This is the eleventh long prose item in the list."
    )


def test_geometry_unwraps_wide_roman_prose_sequence() -> None:
    result = convert_html_table(
        "<table><tr><td>i)</td><td>This is the first long prose item in the list.</td></tr>"
        "<tr><td>ii)</td><td>This is the second long prose item in the list.</td></tr>"
        "<tr><td>iii)</td><td>This is the third long prose item in the list.</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    text = "<TABLE>rendered roman rows</TABLE>"

    assert cleanup_false_tables(text, (geometry,)) == (
        "i) This is the first long prose item in the list.\n"
        "ii) This is the second long prose item in the list.\n"
        "iii) This is the third long prose item in the list."
    )


def test_false_table_cleanup_drops_unwrapped_geometry() -> None:
    result = convert_html_table("<table><tr><td>One row</td></tr></table>")
    geometry = TableGeometry(table_index=0, render_result=result)

    text, retained = cleanup_false_tables_with_metadata(
        "<TABLE>One row</TABLE>", (geometry,)
    )

    assert text == "One row"
    assert retained == ()


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
