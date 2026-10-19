"""Tests for ASCII Form 4 table and footnote section extraction."""

from edgar_sec.engine.forms.ownership.ascii_shape import AsciiShape
from edgar_sec.engine.forms.ownership.ascii_tables import (
    extract_ascii_tables_and_footnotes,
)
from edgar_sec.engine.forms.ownership.securities import (
    parse_table_i_rows,
    parse_table_ii_rows,
)


def test_extract_sc_table_i() -> None:
    text = (
        "<TABLE>\n"
        "<CAPTION>\n"
        "Table I - Non-Derivative Securities Acquired, Disposed of, or Beneficially Owned\n"
        "<S>              <C>          <C>    <C>      <C>      <C>    <C>\n"
        "1. Title         2. Date      3.Code 4.Amount 5.Owned  6.Form 7.Nature\n"
        "Common Stock     05/15/2002   P      500 A    500      D\n"
        "</TABLE>\n"
    )
    t1, t2, fns = extract_ascii_tables_and_footnotes(text, AsciiShape.SC_DASH_RULES)
    assert t1 is not None
    rows = parse_table_i_rows(t1)
    assert len(rows) == 1
    assert rows[0].security_title == "Common Stock"
    assert rows[0].shares_amount == "500"


def test_extract_pipe_table_ii() -> None:
    text = (
        "<TABLE>\n"
        "Table II - Derivative Securities\n"
        "|-------------------------------------------------------------------------------------------------------------------------------|\n"
        "|Title of Deriv|Price |Date   |Code|Number|Date Ex|Exp Date|Underlying|Amt |Price2|Beneficial|Form|Nature|\n"
        "|--------------|------|-------|----|------|-------|--------|----------|----|------|----------|----|------|\n"
        "|Stock Option  |$44.43|1/2/03 |A   |400   |1/2/03 |1/2/13  |Common    |400 |---   |400       |D   |      |\n"
        "|--------------|------|-------|----|------|-------|--------|----------|----|------|----------|----|------|\n"
        "</TABLE>\n"
    )
    t1, t2, fns = extract_ascii_tables_and_footnotes(text, AsciiShape.PIPE_UNDERSCORE)
    assert t2 is not None
    rows = parse_table_ii_rows(t2)
    assert len(rows) == 1
    assert rows[0].security_title == "Stock Option"
    assert rows[0].conversion_or_exercise_price == "44.43"


def test_extract_footnotes() -> None:
    text = (
        "<TABLE>\nTable I\n</TABLE>\n"
        "Explanation of Responses:\n"
        "(1) Options vest in three equal annual installments.\n"
        "/s/ John Smith\n"
    )
    t1, t2, fns = extract_ascii_tables_and_footnotes(text, AsciiShape.SC_ONLY)
    assert len(fns) >= 1
    assert "vest in three" in " ".join(
        cell for section in fns for row in section.resolved_grid.rows for cell in row
    )


def test_caption_stripping_and_pipe_date_wrapping() -> None:
    text = (
        "<TABLE>\n"
        "Table I - Non-Derivative Securities\n"
        "<CAPTION>\n"
        "Common Stock <CAPTION> | 05/15/2002 | P | 100 | 100 | D |\n"
        "</TABLE>\n"
        "<TABLE>\n"
        "Table II - Derivative Securities\n"
        "Option(4)    |21.25 | | | | | |1/2/9|1/2/0|Common|5,000| |5,000|D| |\n"
        "             |      | | | | | |9    |8    |      |     | |     | | |\n"
        "</TABLE>\n"
    )
    t1, t2, fns = extract_ascii_tables_and_footnotes(text, AsciiShape.PIPE_UNDERSCORE)
    assert t1 is not None
    r1 = parse_table_i_rows(t1)
    assert len(r1) == 1
    assert r1[0].security_title == "Common Stock"
    assert "<CAPTION>" not in r1[0].security_title

    assert t2 is not None
    r2 = parse_table_ii_rows(t2, reference_year=2008)
    assert len(r2) == 1
    assert r2[0].exercisable_date == "1999-01-02"
    assert r2[0].expiration_date == "2008-01-02"
