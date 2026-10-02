"""Full-table ASCII rendering: the canonical form and its layout guarantees."""

from __future__ import annotations

import re

import pytest

from edgar_sec.engine.tables.ascii_html.converter import convert_html_table
from edgar_sec.engine.tables.ascii_html.model import RenderBudget

CANONICAL_HTML = """
<table>
  <tr>
    <th align="left" style="border-bottom: 1px solid black;"><b>Component</b></th>
    <th align="right" style="border-bottom: 1px solid black;"><b>2024</b></th>
    <th align="right" style="border-bottom: 1px solid black;"><b>2023</b></th>
  </tr>
  <tr><td>Total revenues</td><td align="right">1,200</td><td align="right">1,100</td></tr>
  <tr><td>Cost of sales</td><td align="right">400</td><td align="right">350</td></tr>
</table>
"""


_ORPHAN_DIVIDER_FRAGMENT_RE = re.compile(r"(?<= )[-=](?= )")


def _lines(html: str, **kwargs) -> list[str]:
    return convert_html_table(html, **kwargs).ascii_text.splitlines()


def test_a_rendered_table_is_wrapped_in_canonical_tags() -> None:
    text = convert_html_table(CANONICAL_HTML).ascii_text
    assert text.startswith("<TABLE>")
    assert text.endswith("</TABLE>")
    assert "Component" in text
    assert "Total revenues" in text
    assert "1,200" in text
    assert "---" in text


def test_a_canonical_table_reports_high_confidence() -> None:
    assert convert_html_table(CANONICAL_HTML).confidence >= 0.80


def test_two_adjacent_identical_tables_do_not_cross_contaminate() -> None:
    from edgar_sec.engine.tables.ascii_html.converter import (
        convert_html_tables_to_ascii,
    )

    html = (
        "<table><tr><td>Date:</td><td>February 18, 2025</td></tr></table>"
        "<table><tr><td>Date:</td><td>February 18, 2025</td></tr></table>"
    )
    assert convert_html_tables_to_ascii(html).count("February 18, 2025") == 2


def test_an_empty_table_produces_no_text_and_states_why() -> None:
    result = convert_html_table("<table></table>")
    assert result.ascii_text == ""
    assert result.confidence == 0.0
    assert "Empty source table" in result.diagnostics


def test_a_table_of_only_whitespace_produces_no_text() -> None:
    result = convert_html_table("<table><tr><td>   </td></tr></table>")
    assert result.ascii_text == ""


def test_html_with_no_table_tag_states_that_no_table_was_found() -> None:
    result = convert_html_table("<p>nothing here</p>")
    assert result.ascii_text == ""
    assert "No <table> tag found" in result.diagnostics


def test_a_dot_leader_in_a_cell_is_reduced_and_cannot_eat_the_column() -> None:
    lines = _lines(
        "<table><tr><td>Operating expenses" + "." * 52 + "</td><td>12</td></tr></table>"
    )
    body = "\n".join(lines)
    assert "Operating expenses..." in body
    assert "...." not in body


def test_a_standalone_dash_does_not_attach_to_the_following_numeric_cell() -> None:
    lines = _lines(
        "<table><tr><th>Current</th><th>Prior</th></tr>"
        "<tr><td>-</td><td>250,000</td></tr></table>"
    )
    line = next(line for line in lines if "250,000" in line)
    assert line.index("250,000") - line.index("-") >= 2


def test_a_spanned_title_does_not_widen_the_operator_column() -> None:
    result = convert_html_table(
        "<table><tr><td colspan='2'>Net Asset Value Calculation</td></tr>"
        "<tr><td align='right'>+</td><td>PV-10 Proved Developed Producing Reserves</td></tr>"
        "<tr><td align='right'>-</td><td>Debt</td></tr></table>"
    )
    assert result.resolved_grid.column_widths[0] <= 6
    assert " +    PV-10" not in result.ascii_text


def test_a_rowspan_header_emits_its_text_once() -> None:
    text = convert_html_table(
        "<table><tr><th rowspan='2'><b>Period ended</b></th>"
        "<th colspan='2'><b>2025</b></th></tr>"
        "<tr><th>Amount</th><th>Rate</th></tr>"
        "<tr><td>Category 1</td><td>100</td><td>5%</td></tr></table>"
    ).ascii_text
    assert text.count("Period ended") == 1


def test_non_breaking_spaces_never_leak_into_the_output() -> None:
    text = convert_html_table(
        "<table><tr><th colspan='2'>Weighted&#xa0;Average<br/>"
        "Grant-Date&#xa0;Fair&#xa0;Value</th></tr>"
        "<tr><td>100</td><td>200</td></tr></table>"
    ).ascii_text
    assert "\xa0" not in text
    header_lines = [
        line for line in text.splitlines() if "Weighted" in line or "Grant" in line
    ]
    assert len(header_lines) == 1
    assert "Weighted Average Grant-Date Fair Value" in header_lines[0]


def test_a_row_header_cell_is_not_duplicated_across_its_continuation_rows() -> None:
    lines = _lines(
        "<table><tr><th>Category</th><th>Item</th></tr>"
        "<tr><td rowspan='2'>Segment A</td><td>First</td></tr>"
        "<tr><td>Second</td></tr></table>"
    )
    assert sum("Segment A" in line for line in lines) == 1


def test_effective_indentation_normalizes_to_two_space_tiers() -> None:
    lines = _lines(
        "<table><tr><th>Year Ended June 30,</th><th>2025</th></tr>"
        "<tr><td style='text-indent: 12.25pt;'>Revenue:</td><td>100</td></tr>"
        "<tr><td style='text-indent: 24.5pt;'>Product</td><td>60</td></tr>"
        "<tr><td style='text-indent: 36pt;'>Total revenue</td><td>100</td></tr></table>"
    )
    assert next(line for line in lines if "Revenue:" in line).startswith("  Revenue:")
    assert next(line for line in lines if "Product" in line).startswith("    Product")
    assert next(line for line in lines if "Total revenue" in line).startswith(
        "    Total revenue"
    )


def test_a_rowspan_description_distributes_across_its_rows_without_a_huge_gap() -> None:
    lines = [
        line.strip()
        for line in _lines(
            "<table><tr><th>Category</th><th>Item</th></tr>"
            "<tr><td rowspan='2'>Segment A</td><td>First activity</td></tr>"
            "<tr><td>Second activity</td></tr></table>"
        )
        if line.strip()
    ]
    first = next(i for i, line in enumerate(lines) if "First activity" in line)
    second = next(i for i, line in enumerate(lines) if "Second activity" in line)
    assert second - first <= 3


def test_vertical_bottom_alignment_puts_a_multi_line_header_on_the_divider_row() -> (
    None
):
    text = convert_html_table(
        "<table>"
        "<tr>"
        "<td width='10' valign='bottom' style='border-bottom: 1px solid #000;'>"
        "<p>Clover</p></td>"
        "<td width='10' valign='bottom' style='border-bottom: 1px solid #000;'>"
        "<p>North Anna</p></td>"
        "<td width='10' valign='bottom' style='border-bottom: 1px solid #000;'>"
        "<p>Combustion Turbine Facilities</p></td>"
        "</tr>"
        "<tr><td>$ 100</td><td>$ 200</td><td>$ 300</td></tr>"
        "</table>",
        budget=RenderBudget(max_column_width=10, max_table_width=40),
    ).ascii_text
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    table_idx = lines.index("<TABLE>")
    divider_idx = next(i for i, line in enumerate(lines) if "---" in line)
    header_block = lines[table_idx + 1 : divider_idx]
    assert len(header_block) == 2
    assert "Combustion Turbine" in header_block[0]
    assert "Clover" not in header_block[0]
    assert "Clover" in header_block[1]
    assert "North Anna" in header_block[1]
    assert "Facilities" in header_block[1]


def test_a_combined_currency_value_ends_at_its_expanded_header_divider() -> None:
    lines = _lines(
        "<table><tr>"
        "<th style='border-bottom: 1px solid black;'>Item</th>"
        "<th colspan='3' style='border-bottom: 1px solid black;'>2017</th></tr>"
        "<tr><td>Income</td><td></td><td>$14,164</td><td></td></tr></table>"
    )
    divider = next(line for line in lines if set(line) <= {"-", " "} and "-" in line)
    value = next(line for line in lines if "$14,164" in line)
    assert value.index("$14,164") + len("$14,164") == divider.rindex("-") + 1


def test_a_value_block_keeps_its_right_edge_across_populated_and_empty_rows() -> None:
    lines = _lines(
        "<table>"
        "<tr><td>Revenue</td><td>$</td><td>67,030</td><td></td><td></td></tr>"
        "<tr><td>Net income</td><td>$</td><td>(127,110</td><td>)</td><td>(1)</td></tr>"
        "<tr><td>Other</td><td>$</td><td>-</td><td></td><td></td></tr>"
        "</table>"
    )
    revenue = next(line for line in lines if "67,030" in line)
    loss = next(line for line in lines if "(127,110)" in line)
    dash = next(line for line in lines if "$ -" in line)
    assert len(revenue.rstrip()) == len(loss.rstrip()) == len(dash.rstrip())


def test_the_output_has_no_blank_row_between_a_row_and_its_divider() -> None:
    lines = _lines(CANONICAL_HTML)
    assert "" not in [line for line in lines if False]
    for index, line in enumerate(lines):
        if set(line) <= {"-", "=", " "} and set(line) & {"-", "="}:
            assert lines[index - 1] != ""


def test_a_rendered_divider_never_contains_a_one_character_orphan_fragment() -> None:
    html = (
        "<table><tr><th>Item</th><th></th><th>Amount</th><th></th></tr>"
        "<tr><td>Revenue</td><td>$</td><td>1,200</td><td>(1)</td></tr></table>"
    )
    text = convert_html_table(html).ascii_text
    assert not _ORPHAN_DIVIDER_FRAGMENT_RE.search(text)


def test_a_very_long_single_cell_wraps_rather_than_overflowing_the_budget() -> None:
    budget = RenderBudget(max_table_width=30, max_column_width=20)
    text = convert_html_table(
        "<table><tr><td>" + "word " * 40 + "</td></tr></table>", budget=budget
    ).ascii_text
    body = [line for line in text.splitlines() if line not in ("<TABLE>", "</TABLE>")]
    assert all(len(line) <= budget.max_table_width for line in body)


@pytest.mark.parametrize("html", ["", "   ", "<p>x</p>"])
def test_render_is_defined_for_degenerate_input(html: str) -> None:
    result = convert_html_table(html)
    assert isinstance(result.ascii_text, str)
    assert 0.0 <= result.confidence <= 1.0
