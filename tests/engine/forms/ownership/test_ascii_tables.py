"""Tests for ASCII Form 4 table and footnote parsing."""

from edgar_sec.engine.forms.ownership.ascii_shape import AsciiShape
from edgar_sec.engine.forms.ownership.ascii_tables import (
    extract_ascii_tables_and_footnotes,
)
from edgar_sec.engine.forms.ownership.securities import (
    parse_footnotes,
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
    assert rows[0].shares_amount == 500.0


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
    assert rows[0].conversion_or_exercise_price == 44.43


def test_extract_footnotes() -> None:
    text = (
        "<TABLE>\nTable I\n</TABLE>\n"
        "Explanation of Responses:\n"
        "(1) Options vest in three equal annual installments.\n"
        "/s/ John Smith\n"
    )
    t1, t2, fns = extract_ascii_tables_and_footnotes(text, AsciiShape.SC_ONLY)
    assert len(fns) >= 1
    fn_map = parse_footnotes(fns)
    assert "1" in fn_map
    assert "vest in three" in fn_map["1"]
