"""Unit tests for engine common tabular grid partitioning."""

from edgar_sec.engine.forms.common.tables import (
    address_from_column_headers,
    extract_labeled_field,
    is_empty_continuation_row,
    is_instruction_row,
    parse_address_parts,
    partition_grid_rows,
)
from edgar_sec.engine.tables.ascii_html.converter import ResolvedGrid


def test_is_instruction_row():
    """Verify detection of instructional prose and statutory markers."""
    instr = "If the securities were purchased and full payment therefor was not made in cash"
    assert is_instruction_row(instr)
    assert is_instruction_row("See 18 U.S.C. 1001 for criminal violations")
    assert not is_instruction_row("Common Stock 01/15/2020 RSU Grant 5,000")


def test_partition_grid_rows():
    """Verify row separation into header, data, and instructions."""
    rows = (
        ("TABLE I - SECURITIES TO BE SOLD",),
        ("Title of the Class", "Date Acquired", "Amount Acquired"),
        ("Common Stock", "01/15/2020", "5,000"),
        ("INSTRUCTIONS: payment therefor was not made in cash",),
    )
    grid = ResolvedGrid(rows=rows, column_alignments=(), column_widths=())
    partition = partition_grid_rows(
        grid, {"title", "class", "date", "amount"}, min_header_score=2
    )

    assert partition.header_index == 1
    assert len(partition.data_rows) == 1
    assert partition.data_rows[0][0] == "Common Stock"
    assert len(partition.instruction_rows) == 1


def test_extract_labeled_field_inline_and_adjacent():
    """Verify inline tail and adjacent-cell 2D coordinate lookups."""
    rows = (
        ("1 (a) NAME OF ISSUER: Acme International Inc.", "1 (b) IRS: 12-3456789"),
        ("1 (c) S.E.C. FILE NO.", "001-99999"),
        ("2 (a) NAME OF PERSON", ""),
        ("Jane Smith", "Officer"),
    )
    grid = ResolvedGrid(rows=rows, column_alignments=(), column_widths=())

    name = extract_labeled_field(grid, ("name of issuer", "1 (a)"))
    assert name == "Acme International Inc."

    sec_file = extract_labeled_field(grid, ("s.e.c. file no.", "1 (c)"))
    assert sec_file == "001-99999"

    person = extract_labeled_field(grid, ("name of person", "2 (a)"))
    assert person == "Jane Smith"


def test_parse_address_helpers():
    """Verify address parsing from formatted text and column headers."""
    street, city, state, zip_c = parse_address_parts(
        "100 Main Street, Suite 400, Chicago, IL 60601"
    )
    assert street == "100 Main Street, Suite 400"
    assert city == "Chicago"
    assert state == "IL"
    assert zip_c == "60601"

    cols = ("STREET", "CITY", "STATE", "ZIP CODE")
    vals = ("500 Broadway", "New York", "NY", "10012")
    c_street, c_city, c_state, c_zip = address_from_column_headers(cols, vals)
    assert c_street == "500 Broadway"
    assert c_city == "New York"
    assert c_state == "NY"
    assert c_zip == "10012"


def test_parse_address_resolves_non_us_jurisdiction_names():
    street, city, country, zip_code = parse_address_parts(
        "123 Main Street, Toronto, Ontario, Canada"
    )

    assert (street, city, country, zip_code) == (
        "123 Main Street",
        "Toronto",
        "A6",
        None,
    )


def test_extract_labeled_field_proportional_column_mapping():
    """Verify proportional column lookdown across variable-width grid rows."""
    rows = (
        ("1.", "Reporting Person", "2.", "Issuer Name and Ticker", "3.", "IRS No."),
        ("Macali, Ralph D.", "Farmers National Banc Corp./FMNB.OB"),
    )
    grid = ResolvedGrid(rows=rows, column_alignments=(), column_widths=())
    issuer = extract_labeled_field(grid, ("issuer name", "name of issuer"))
    assert issuer == "Farmers National Banc Corp./FMNB.OB"


def test_is_empty_continuation_row() -> None:
    assert is_empty_continuation_row(("None", "", "N/A"))
    assert is_empty_continuation_row(("no reported", "nil", "0"))
    assert is_empty_continuation_row(())
    assert not is_empty_continuation_row(("None", "1,000"))
