"""Tests for Form 4 Table I, Table II, and Footnotes parsing."""

from edgar_sec.engine.forms.ownership.grid_tables import (
    parse_footnotes,
    parse_table_i_rows,
    parse_table_ii_rows,
)
from edgar_sec.engine.forms.ownership.sections import partition_form4_tables

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


def test_parse_table_i_and_table_ii_rows() -> None:
    sections = partition_form4_tables(SAMPLE_TABLES_HTML)

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
