"""Tests for ownership Table I (Non-Derivative) row extraction."""

from edgar_sec.engine.forms.common.numbers import extract_schema_number
from edgar_sec.engine.forms.ownership.sections import partition_ownership_tables
from edgar_sec.engine.forms.ownership.table_i import parse_table_i_rows

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
    assert extract_schema_number("00123") == "123"
    assert extract_schema_number("1,234.50") == "1234.50"
    assert extract_schema_number("$8.00") == "8.00"
    assert extract_schema_number("123456789012345678.90") == "123456789012345678.90"
    assert extract_schema_number("²") is None


def test_parse_table_i_and_table_ii_rows() -> None:
    sections = partition_ownership_tables(SAMPLE_TABLES_HTML)

    t1_rows = parse_table_i_rows(sections.table_i)
    assert len(t1_rows) == 2
    assert t1_rows[0].security_title == "Common Stock"
    assert t1_rows[0].transaction_date == "1999-04-01"
    assert t1_rows[0].transaction_code == "G"
    assert t1_rows[0].equity_swap_involved is True
    assert t1_rows[0].shares_amount == "3000"
    assert t1_rows[0].acquired_disposed_code == "D"
    assert t1_rows[0].shares_owned_following == "23337"
    assert t1_rows[0].direct_or_indirect == "D"
    assert t1_rows[0].footnote_ids == ("1",)

    assert t1_rows[1].direct_or_indirect == "I"
    assert t1_rows[1].nature_of_ownership == "By 401(k) Plan"
    assert t1_rows[1].shares_owned_following == "541.158"


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
    rows = parse_table_i_rows(sections.table_i, reference_year=2002)

    assert len(rows) == 1
    assert rows[0].transaction_date == "2002-07-30"
    assert rows[0].transaction_code == "S"
    assert rows[0].shares_amount == "5000"
    assert rows[0].acquired_disposed_code == "D"
    assert rows[0].price_per_share == "8"
    assert rows[0].shares_owned_following == "51500"
    assert rows[0].direct_or_indirect == "D"


def test_table_i_keeps_nature_in_its_column_when_source_omits_ownership_form() -> None:
    html = """<html><body>
    <table><tr><td>Table I - Non-Derivative Securities</td></tr></table>
    <table>
      <tr>
        <td>1. Title of Security</td><td>2. Transaction Date</td>
        <td>3. Deemed Execution Date</td><td>4. Transaction Code</td>
        <td>5. Equity Swap</td><td>6. Shares</td><td>7. Acquired/Disposed</td>
        <td>8. Price</td><td>9. Shares Owned Following</td>
        <td>10. Ownership Form</td><td>11. Nature</td>
      </tr>
      <tr>
        <td>Common Stock</td><td>04/01/1999</td><td></td><td>P</td><td></td>
        <td>100</td><td>A</td><td>$1.00</td><td>200</td><td></td><td>By spouse</td>
      </tr>
    </table>
    </body></html>"""

    rows = parse_table_i_rows(partition_ownership_tables(html).table_i)

    assert len(rows) == 1
    assert rows[0].shares_owned_following == "200"
    assert rows[0].direct_or_indirect is None
    assert rows[0].nature_of_ownership == "By spouse"


def test_accession_0000950138_02_000382_carries_title_and_equity_swap_marker() -> None:
    html = """<html><body>
    <table><tr><td>Table I - Non-Derivative Securities</td></tr></table>
    <table>
      <tr>
        <td>1. Title of Security</td><td>2. Transaction Date</td>
        <td>3. Deemed Execution Date</td><td>4. Transaction Code</td>
        <td>5. Equity Swap</td><td>6. Shares</td><td>7. Acquired/Disposed</td>
        <td>8. Price</td><td>9. Shares Owned Following</td>
        <td>10. Ownership Form</td><td>11. Nature</td>
      </tr>
      <tr>
        <td>Common Stock</td><td>11/18/02</td><td></td><td>G</td><td>V</td>
        <td>950</td><td>D</td><td></td><td>252,184</td><td>D</td><td></td>
      </tr>
      <tr>
        <td></td><td></td><td></td><td>G</td><td>V</td><td>500</td><td>A</td>
        <td></td><td>34,278</td><td>I</td><td>Spouse</td>
      </tr>
    </table>
    </body></html>"""

    rows = parse_table_i_rows(partition_ownership_tables(html).table_i)

    assert len(rows) == 2
    assert rows[1].security_title == "Common Stock"
    assert rows[1].transaction_code == "G"
    assert rows[1].equity_swap_involved is True
    assert rows[1].shares_amount == "500"
    assert rows[1].acquired_disposed_code == "A"
    assert rows[1].shares_owned_following == "34278"
    assert rows[1].direct_or_indirect == "I"
    assert rows[1].nature_of_ownership == "Spouse"
