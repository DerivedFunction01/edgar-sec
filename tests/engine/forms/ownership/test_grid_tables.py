"""Tests for Form 4 Table I, Table II, and Footnotes parsing."""

from dataclasses import replace

from edgar_sec.engine.forms.ownership.grid_tables import (
    _extract_number,
    parse_footnotes,
    parse_table_i_rows,
    parse_table_ii_rows,
)
from edgar_sec.engine.forms.ownership.sections import partition_ownership_tables

SAMPLE_TABLES_HTML = """
<html><body>
<table><tr><td>Table I - Non-Derivative Securities Acquired, Disposed of, or Beneficially Owned</td></tr></table>
<table>
  <tr>
    <td>1. Title of Security</td><td>2. Trans Date</td><td>3. Code</td>
    <td>4. Amount | A/D | Price</td><td>5. End of Month</td><td>6. Form</td><td>7. Nature</td>
  </tr>
  <tr>
    <td>Common Stock</td><td>04/01/1999 (1)</td><td>G | V</td>
    <td>3,000.000 | D |</td><td>23,337.000</td><td>D</td><td></td>
  </tr>
  <tr>
    <td>Common Stock</td><td></td><td></td>
    <td></td><td>541.158</td><td>I</td><td>By 401(k) Plan</td>
  </tr>
</table>
<table><tr><td>Table II - Derivative Securities Acquired, Disposed of, or Beneficially Owned</td></tr></table>
<table>
  <tr>
    <td>1. Title of Derivative Security</td><td>2. Exercise Price</td><td>3. Trans Date</td>
    <td>4. Code</td><td>5. Amount</td><td>6. Date Exercisable and Exp Date</td>
    <td>7. Title and Amount Underlying</td><td>8. Price</td><td>9. End of Month</td><td>10. Form</td><td>11. Nature</td>
  </tr>
  <tr>
    <td>1996 Stock Option</td><td>$18.7500</td><td></td>
    <td></td><td></td><td>07/25/1997 | 07/25/2006</td>
    <td>Common Stock - 7,550.000</td><td></td><td>7,550.000</td><td>D</td><td></td>
  </tr>
</table>
<table><tr><td>
  Explanation of Responses:
  (1) Gift of shares to charitable foundation.
</td></tr></table>
</body></html>
"""


def test_extract_number_fast_path_preserves_numeric_fallbacks() -> None:
    assert _extract_number("00123") == 123.0
    assert _extract_number("1,234.50") == 1234.5
    assert _extract_number("$8.00") == 8.0
    assert _extract_number("²") is None


def test_parse_table_i_and_table_ii_rows() -> None:
    sections = partition_ownership_tables(SAMPLE_TABLES_HTML)

    t1_rows = parse_table_i_rows(sections.table_i)
    assert len(t1_rows) == 2
    assert t1_rows[0].security_title == "Common Stock"
    assert t1_rows[0].transaction_date == "04/01/1999"
    assert t1_rows[0].transaction_code == "G"
    assert t1_rows[0].equity_swap_involved is True
    assert t1_rows[0].shares_amount == 3000.0
    assert t1_rows[0].acquired_disposed_code == "D"
    assert t1_rows[0].shares_owned_following == 23337.0
    assert t1_rows[0].direct_or_indirect == "D"
    assert t1_rows[0].footnote_ids == ("1",)

    assert t1_rows[1].direct_or_indirect == "I"
    assert t1_rows[1].nature_of_ownership == "By 401(k) Plan"
    assert t1_rows[1].shares_owned_following == 541.158

    t2_rows = parse_table_ii_rows(sections.table_ii)
    assert len(t2_rows) == 1
    assert t2_rows[0].security_title == "1996 Stock Option"
    assert t2_rows[0].conversion_or_exercise_price == 18.75
    assert t2_rows[0].exercisable_date == "07/25/1997"
    assert t2_rows[0].expiration_date == "07/25/2006"
    assert t2_rows[0].underlying_security_title == "Common Stock"
    assert t2_rows[0].underlying_shares_amount == 7550.0

    footnotes = parse_footnotes(sections.footnotes)
    assert footnotes.get("1") == "Gift of shares to charitable foundation."


def test_parse_footnotes_finds_all_entries_in_multiline_cell() -> None:
    sections = partition_ownership_tables(SAMPLE_TABLES_HTML)
    source = sections.footnotes[0]
    grid = replace(
        source.resolved_grid,
        rows=(
            (
                "Explanation of Responses:\n"
                "  (1) Gift of shares to charitable foundation.\n"
                "  [2] Shares acquired under the applicable plan.",
            ),
        ),
    )

    footnotes = parse_footnotes([replace(source, resolved_grid=grid)])

    assert footnotes == {
        "1": "Gift of shares to charitable foundation.",
        "2": "Shares acquired under the applicable plan.",
    }


def test_parse_table_ii_strips_header_leaks() -> None:
    html = """<html><body>
    <table><tr><td>Table II - Derivative Securities Acquired</td></tr></table>
    <table>
      <tr>
        <td>1. Title of Derivative</td><td>2. Exercise Price</td><td>3. Trans Date</td>
        <td>4. Code</td><td>5. Amount</td><td>6. Date Exercisable and Exp Date</td>
        <td>7. Title and Amount Underlying</td><td>8. Price</td><td>9. End of Month</td><td>10. Form</td><td>11. Nature</td>
      </tr>
      <tr>
        <td>Deemed Execution Date, if any (Month/Day/Year)</td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td>
      </tr>
      <tr>
        <td>Employee Stock Option</td><td>$10.00</td><td>06/01/2001</td>
        <td>A</td><td>100</td><td>06/01/2002 | 06/01/2011</td>
        <td>Deemed Execution Date, if any (Month/Day/Year)</td><td></td><td>100</td><td>D</td><td></td>
      </tr>
    </table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    t2_rows = parse_table_ii_rows(sections.table_ii)
    assert len(t2_rows) == 1
    assert t2_rows[0].security_title == "Employee Stock Option"
    assert t2_rows[0].underlying_security_title is None


def test_table_i_resolves_multiline_header_columns() -> None:
    html = """<html><body><table>
    <tr><td></td><td colspan="9">Table I - Non-Derivative Securities Acquired, Disposed of, or Beneficially Owned</td></tr>
    <tr>
      <td>1. Title of Security</td><td>2. Transaction Date (Month/Day/Year)</td>
      <td colspan="2">3. Transaction Code (Instr. 8)</td>
      <td colspan="3">4. Securities Acquired (A) or Disposed of (D)</td>
      <td>5. Amount of Securities Beneficially Owned at End of Month</td>
      <td>6. Ownership Form: Direct (D) or Indirect (I)</td>
      <td>7. Nature of Indirect Beneficial Ownership</td>
    </tr>
    <tr>
      <td></td><td></td><td>Code</td><td>V</td><td>Amount</td>
      <td>(A) or (D)</td><td>Price</td><td></td><td></td><td></td>
    </tr>
    <tr>
      <td>Common Stock, $.10 par value</td><td>7/30/02</td><td>S</td><td></td>
      <td>5,000</td><td>(D)</td><td>$8/shr</td><td>51,500</td><td>(D)</td><td></td>
    </tr>
    </table></body></html>"""

    sections = partition_ownership_tables(html)
    rows = parse_table_i_rows(sections.table_i)

    assert len(rows) == 1
    assert rows[0].transaction_date == "7/30/02"
    assert rows[0].transaction_code == "S"
    assert rows[0].shares_amount == 5000.0
    assert rows[0].acquired_disposed_code == "D"
    assert rows[0].price_per_share == 8.0
    assert rows[0].shares_owned_following == 51500.0
    assert rows[0].direct_or_indirect == "D"


def test_table_ii_resolves_split_amount_date_and_underlying_columns() -> None:
    html = """<html><body><table>
    <tr><td>FORM 4 (continued)</td><td colspan="15">Table II - Derivative Securities Acquired, Disposed of, or Beneficially Owned</td></tr>
    <tr>
      <td>1. Title of Derivative Security</td><td>2. Conversion or Exercise Price</td>
      <td>3. Transaction Date (Month/Day/Year)</td><td>3A. Deemed Execution Date</td>
      <td colspan="2">4. Transaction Code (Instr. 8)</td>
      <td colspan="2">5. Number of Derivative Securities Acquired (A) or Disposed of (D)</td>
      <td colspan="2">6. Date Exercisable and Expiration Date</td>
      <td colspan="2">7. Title and Amount of Underlying Securities</td>
      <td>8. Price of Derivative Security</td><td>9. Number Beneficially Owned Following</td>
      <td>10. Ownership Form: Direct (D) or Indirect (I)</td><td>11. Nature of Indirect Ownership</td>
    </tr>
    <tr>
      <td></td><td></td><td></td><td></td><td>Code</td><td>V</td>
      <td>(A)</td><td>(D)</td><td>Date Exercisable</td><td>Expiration Date</td>
      <td>Title</td><td>Amount or Number of Shares</td><td></td><td></td><td></td><td></td>
    </tr>
    <tr>
      <td>Employee Stock Option (right to buy)</td><td>$31.4650</td><td>02/11/03</td><td></td>
      <td>A</td><td></td><td>50,000</td><td></td><td>02/11/06</td><td>02/11/13</td>
      <td>Common Stock</td><td>50,000</td><td></td><td>50,000</td><td>(D)</td><td></td>
    </tr>
    </table></body></html>"""

    sections = partition_ownership_tables(html)
    rows = parse_table_ii_rows(sections.table_ii)

    assert len(rows) == 1
    assert rows[0].security_title == "Employee Stock Option (right to buy)"
    assert rows[0].conversion_or_exercise_price == 31.465
    assert rows[0].transaction_date == "02/11/03"
    assert rows[0].transaction_code == "A"
    assert rows[0].shares_amount == 50000.0
    assert rows[0].acquired_disposed_code == "A"
    assert rows[0].exercisable_date == "02/11/06"
    assert rows[0].expiration_date == "02/11/13"
    assert rows[0].underlying_security_title == "Common Stock"
    assert rows[0].underlying_shares_amount == 50000.0
    assert rows[0].derivative_shares_owned_following == 50000.0
    assert rows[0].direct_or_indirect == "D"


def test_4977_03_000095_maps_nested_header_and_skips_artifacts() -> None:
    template = """<html><body><table>
    <tr><td>Table II - Derivative Securities Acquired</td></tr>
    <tr><td>1. Title of Derivative Security</td></tr>
    <tr><td>Employee Stock Option</td></tr>
    </table></body></html>"""
    section = partition_ownership_tables(template).table_ii
    assert section is not None

    def row(*cells: str) -> tuple[str, ...]:
        return (*cells, *("" for _ in range(19 - len(cells))))

    grid_rows = (
        row("Reminder: Report on a separate line for each class of securities"),
        row("*"),
        row("", "", "", "", "", "", "", "", "OMB information"),
        row("FORM 4 (continued)", "Table II - Derivative Securities Acquired"),
        row(
            "1. Title of Derivative Security",
            "",
            "2. Conversion or Exercise Price of Derivative Security",
            "3. Transaction Date",
            "3A. Deemed Execution Date",
            "4. Transaction Code (Instr. 8)",
            "",
            "5. Number of Derivative Securities Acquired (A) or Disposed of (D)",
            "",
            "",
            "6. Date Exercisable and Expiration Date",
            "",
            "7. Title and Amount of Underlying Securities",
            "",
            "8. Price of Derivative Security",
            "9. Number Beneficially Owned Following",
            "10. Ownership Form: Direct (D) or Indirect (I)",
            "",
            "11. Nature of Indirect Ownership",
        ),
        row(
            "",
            "",
            "",
            "",
            "",
            "Code",
            "V",
            "(A)",
            "",
            "(D)",
            "Date Exercisable",
            "Expiration Date",
            "Title",
            "Amount or Number of Shares",
        ),
        row(
            "Employee Stock Option (right to buy)",
            "",
            "$4.7084",
            "03/18/03",
            "",
            "M",
            "",
            "",
            "",
            "10,000",
            "06/28/93",
            "06/28/03",
            "Common Stock",
            "10,000",
            "",
            "14,290",
            "D",
        ),
    )
    resolved_grid = replace(section.resolved_grid, rows=grid_rows, header_row_count=0)
    section = replace(section, resolved_grid=resolved_grid)

    rows = parse_table_ii_rows(section)

    assert len(rows) == 1
    assert rows[0].security_title == "Employee Stock Option (right to buy)"
    assert rows[0].transaction_date == "03/18/03"
    assert rows[0].transaction_code == "M"
    assert rows[0].shares_amount == 10000.0
    assert rows[0].acquired_disposed_code == "D"
    assert rows[0].exercisable_date == "06/28/93"
    assert rows[0].expiration_date == "06/28/03"
    assert rows[0].underlying_security_title == "Common Stock"
    assert rows[0].underlying_shares_amount == 10000.0
    assert rows[0].derivative_shares_owned_following == 14290.0


def test_parse_table_ii_ignores_numbered_header_cells_as_data() -> None:
    html = """<html><body>
    <table><tr><td>Table II - Derivative Securities</td></tr></table>
    <table><tr>
      <td>1.</td><td>Title of Derivative Security</td>
      <td>2.</td><td>Conversion or Exercise Price</td>
      <td>3a.</td><td>Title and Amount of Underlying Securities</td>
    </tr></table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    assert parse_table_ii_rows(sections.table_ii) == []
