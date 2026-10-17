"""Tests for Form 144 Table I and Table II extraction in securities.py."""

from edgar_sec.engine.forms.form144.sections import partition_form144_tables
from edgar_sec.engine.forms.form144.securities import (
    parse_table_i_rows,
    parse_table_ii_rows,
)

SAMPLE_HTML = """
<html><body>
<table>
<tr><td>TABLE I - SECURITIES TO BE SOLD</td></tr>
<tr><td>Title of the Class</td><td>Date you Acquired</td><td>Nature of Acquisition Transaction</td><td>Name of Person from Whom Acquired</td><td>Amount Acquired</td><td>Date of Payment</td><td>Nature of Payment</td></tr>
<tr><td>Common Stock</td><td>01/15/2020</td><td>RSU Grant</td><td>Issuer</td><td>5,000</td><td>01/15/2020</td><td>Services</td></tr>
</table>
<table>
<tr><td>TABLE II - SECURITIES SOLD DURING THE PAST 3 MONTHS</td></tr>
<tr><td>Name and Address of Seller</td><td>Title of Securities Sold</td><td>Date of Sale</td><td>Amount of Securities Sold</td><td>Gross Proceeds</td></tr>
<tr><td>Jane Doe</td><td>Common Stock</td><td>03/01/2022</td><td>1,000</td><td>$30,000.00</td></tr>
</table>
</body></html>
"""


def test_parse_tables():
    sections = partition_form144_tables(SAMPLE_HTML)
    table_i = parse_table_i_rows(sections.table_i)
    assert len(table_i) == 1
    assert table_i[0].amount_acquired == 5000
    assert table_i[0].nature_of_acquisition == "RSU Grant"

    nothing_to_report, table_ii = parse_table_ii_rows(sections.table_ii)
    assert not nothing_to_report
    assert len(table_ii) == 1
    assert table_ii[0].amount_sold == 1000
    assert table_ii[0].gross_proceeds == 30000.0


def test_parse_table_i_missing_optional_columns():
    """Verify deficit resolution when payment date and donor columns are omitted."""
    html = """<html><body>
    <table>
      <tr><td>TABLE I - SECURITIES TO BE SOLD</td></tr>
      <tr><td>Common Stock</td><td>02/20/2021</td><td>Direct Purchase</td><td>10,000</td></tr>
    </table>
    </body></html>"""
    sections = partition_form144_tables(html)
    items = parse_table_i_rows(sections.table_i)
    assert len(items) == 1
    assert items[0].class_title == "Common Stock"
    assert items[0].acquired_date == "02/20/2021"
    assert items[0].nature_of_acquisition == "Direct Purchase"
    assert items[0].amount_acquired == 10000
    assert items[0].payment_date == "02/20/2021"
