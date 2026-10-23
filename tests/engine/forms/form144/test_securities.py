"""Tests for Form 144 Table I and Table II extraction in securities.py."""

from edgar_sec.engine.forms.form144.sections import (
    ClassifiedSection,
    SectionRole,
    partition_form144_tables,
)
from edgar_sec.engine.forms.form144.securities import (
    parse_table_i_rows,
    parse_table_ii_rows,
)
from edgar_sec.engine.tables.ascii_html.model import ResolvedGrid

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
    assert table_ii[0].gross_proceeds == "30000.00"


def test_parse_table_ii_splits_seller_name_and_address():
    grid = ResolvedGrid(
        rows=(
            (
                "Name and Address of Seller",
                "Title of Securities Sold",
                "Date of Sale",
                "Amount of Securities Sold",
                "Gross Proceeds",
            ),
            (
                "J.P. Morgan Securities Inc.\n345 Park Avenue\nNew York, NY 10154",
                "Common Stock",
                "2/13/08",
                "10,000",
                "$438,901",
            ),
        ),
        column_alignments=(),
        column_widths=(),
    )
    section = ClassifiedSection(
        role=SectionRole.TABLE_II,
        table_index=0,
        raw_node=None,
        resolved_grid=grid,
    )
    _nothing, table_ii = parse_table_ii_rows(section)
    assert len(table_ii) == 1
    assert table_ii[0].seller_name == "J.P. Morgan Securities Inc."
    assert table_ii[0].seller_address == "345 Park Avenue, New York, NY 10154"


def test_parse_table_i_accepts_full_text_dates():
    grid = ResolvedGrid(
        rows=(
            (
                "Title of the Class",
                "Date You Acquired",
                "Nature of Acquisition Transaction",
                "Name of Person from Whom Acquired",
                "Amount of Securities Acquired",
                "Date of Payment",
                "Nature of Payment",
            ),
            (
                "Common Stock",
                "January 22, 2004",
                "Open market purchase",
                "Issuer",
                "27,859",
                "January 22, 2004",
                "Cash",
            ),
        ),
        column_alignments=(),
        column_widths=(),
    )
    section = ClassifiedSection(
        role=SectionRole.TABLE_I,
        table_index=0,
        raw_node=None,
        resolved_grid=grid,
    )
    items = parse_table_i_rows(section)
    assert len(items) == 1
    assert items[0].acquired_date == "2004-01-22"
    assert items[0].payment_date == "2004-01-22"
    assert items[0].amount_acquired == 27859


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
    assert items[0].acquired_date == "2021-02-20"
    assert items[0].nature_of_acquisition == "Direct Purchase"
    assert items[0].amount_acquired == 10000
    assert items[0].payment_date == "2021-02-20"


VARIOUS_DATE_HTML = """
<html><body>
<table>
<tr><td>TABLE I - SECURITIES TO BE SOLD</td></tr>
<tr><td>Title of the Class</td><td>Date You Acquired</td><td>Nature of Acquisition Transaction</td><td>Name of Person from Whom Acquired</td><td>Amount of Securities Acquired</td><td>Date of Payment</td><td>Nature of Payment</td></tr>
<tr><td>Common $1 Par Value</td><td>Various</td><td>Acquired as a result of awards granted under benefit plans.</td><td>Acquired as a result of awards granted under benefit plans.</td><td>6,025</td><td>Various</td><td>Cash</td></tr>
</table>
</body></html>
"""

WRAPPED_HEADER_HTML = """
<html><body>
<table>
<tr><td>TABLE I - SECURITIES TO BE SOLD</td></tr>
<tr><td>Title of</td><td>Date You</td><td>Name of Acquisition</td><td>Whom Acquired (If gift,</td><td>Amount of</td><td>Date of</td><td>Nature</td></tr>
<tr><td>the Class</td><td>Acquired</td><td>Transaction</td><td>also give date donor acquired)</td><td>Securities Acquired</td><td>Payment</td><td>of Payment</td></tr>
<tr><td>Common Stock</td><td>12/04/2017</td><td>Equity Compensation</td><td>Issuer</td><td>30,000</td><td>12/04/2017</td><td>Cash</td></tr>
</table>
</body></html>
"""


def test_table_i_various_date_row_is_data_not_header():
    sections = partition_form144_tables(VARIOUS_DATE_HTML)
    rows = parse_table_i_rows(sections.table_i)
    assert len(rows) == 1
    assert rows[0].amount_acquired == 6025


def test_table_i_wrapped_header_rows_are_not_data():
    sections = partition_form144_tables(WRAPPED_HEADER_HTML)
    rows = parse_table_i_rows(sections.table_i)
    assert len(rows) == 1
    assert rows[0].class_title == "Common Stock"
    assert rows[0].amount_acquired == 30000
