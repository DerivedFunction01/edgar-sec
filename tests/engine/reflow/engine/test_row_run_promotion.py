"""Row-run promotion: what a confirmed run may absorb, and where it stops.
No test trims a run’s edge back from a caption or heading: `4.  Shareholders’
Equity (Deficit)` and `3.1  Certificate of Incorporation` parse identically.
"""

from __future__ import annotations

from edgar_sec.engine.reflow.engine.rewrapper import reflow_ascii


def test_dot_leader_index_rows_with_repeated_page_columns_are_tagged() -> None:
    text = (
        "PART I\nITEM 1. BUSINESS\n\n"
        "Item 1. Business ................. 1\n"
        "Item 1A. Risk Factors ............ 5\n"
        "Item 2. Properties ............... 8"
    )
    result = reflow_ascii(text, body_start_line=3)
    assert result.text.count("<TABLE>") == 1
    assert result.text.count("</TABLE>") == 1
    assert "<TABLE>\nItem 1. Business ................. 1" in result.text


def test_row_run_merges_a_classified_middle_block_and_trailing_total() -> None:
    rows = (
        "Balance, November 30, 1991....  6,659,000     8,260       352,000      6,337",
        "Incentive shares issued.......        --         (2)           --         (2)",
        "Balance, November 30, 1992....  6,659,000     8,258       352,000      6,335",
        "Shares purchased..............         --        --         7,000         81",
        "Stock options exercised.......         --      (149)      (15,000)      (265)",
    )
    text = "\n\n".join((rows[0], "\n".join(rows[1:4]), rows[4]))
    result = reflow_ascii(text, body_start_line=0)
    assert result.text == f"<TABLE>\n{text}\n</TABLE>"


def test_a_ragged_placeholder_column_does_not_truncate_the_run() -> None:
    # A wrapped label shifts the first cells but the last two still align, so the closing
    # row is not orphaned.
    rows = (
        "Balance, November 30, 1991....  6,659,000     8,260       352,000      6,337",
        "Shares issued in private ",
        "  placement...................  1,283,000    11,485            --         --",
        "Shares purchased..............         --        --         7,000         81",
        "Stock options exercised.......         --      (149)      (15,000)      (265)",
        "Balance, November 30, 1993....  7,942,000   $19,594       191,000     $3,403",
    )
    text = "\n\n".join((rows[0], "\n".join(rows[1:-1]), rows[-1]))
    result = reflow_ascii(text, body_start_line=0)
    assert result.text == f"<TABLE>\n{text}\n</TABLE>"


def test_row_run_stops_before_a_wrapped_ordered_marker() -> None:
    # ``(7)`` parses as a numeric cell, so the boundary comes from block extent rather
    # than from reading the marker.
    rows = (
        "Royce C. McCall        1,234,567         45,231",
        "Bennett S. Alexander      987,654         12,004",
        "Total                     2,222,221         57,235",
    )
    caption = "(7)   Commitments and Contingencies"
    body = "\n\n".join(rows)
    text = f"{body}\n\n{caption}"
    result = reflow_ascii(text, body_start_line=0)
    assert result.text == f"<TABLE>\n{body}\n</TABLE>\n\n{caption}"


def test_row_run_stops_before_an_adjacent_non_row_block() -> None:
    # The heading and legend carry no numeric cell of their own, so neither joins the run.
    rows = (
        "Current assets                 100        90",
        "Property and equipment          200       180",
        "Total assets                     300       270",
    )
    heading = "4.     Shareholders' Equity (Deficit)"
    legend = "*     Management compensation plans and arrangements."
    body = "\n\n".join(rows)
    expected = "<TABLE>\n" + body + "\n</TABLE>"
    for text, want in (
        (f"{heading}\n\n{body}\n\n{legend}", f"{heading}\n\n{expected}\n\n{legend}"),
        (f"{body}\n\n{heading}", f"{expected}\n\n{heading}"),
        (f"{body}\n\n{legend}", f"{expected}\n\n{legend}"),
    ):
        assert reflow_ascii(text, body_start_line=0).text == want


def test_linguistic_numeric_prose_is_not_promoted() -> None:
    # Sentence-shaped lines with a stray percentage must be refused by the cascade, not
    # by geometry.
    text = (
        "      1.   Each person who is known by us to be the beneficial owner of more than\n"
        "           5% of the common stock,\n\n"
        "      2.   Each of our directors and executive officers and\n\n"
        "      3.   All of our directors and executive officers as a group."
    )
    assert "<TABLE>" not in reflow_ascii(text, body_start_line=0).text
