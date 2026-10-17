"""Tests for Form 144 Table I and Table II extraction."""

from edgar_sec.engine.forms.form144.grid_tables import (
    parse_table_i_rows,
    parse_table_ii_rows,
)
from edgar_sec.engine.forms.form144.sections import partition_form144_tables

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
