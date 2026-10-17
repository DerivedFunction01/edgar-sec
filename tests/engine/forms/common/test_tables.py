"""Unit tests for engine common tabular grid partitioning."""

from edgar_sec.engine.forms.common.tables import (
    is_instruction_row,
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
