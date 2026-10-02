"""Table continuation detection and the fusion of a repeated header."""

from __future__ import annotations

from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.engine.tables.ascii_html.continuation import (
    detect_table_continuation,
    fuse_source_tables,
    is_allowed_intervening_content,
)
from edgar_sec.engine.tables.ascii_html.model import SourceTable
from edgar_sec.engine.tables.ascii_html.spans import extract_source_table

STATEMENT_HEAD = "<tr><th>Item</th><th>2017</th><th>2018</th></tr>"


def _table(*rows: str) -> SourceTable:
    html = "<table>" + "".join(rows) + "</table>"
    node = parse_html(html).css_first("table")
    assert node is not None
    source, _ = extract_source_table(node)
    return source


def _a() -> SourceTable:
    return _table(
        STATEMENT_HEAD,
        "<tr><td>Revenue</td><td>1,000</td><td>1,200</td></tr>",
    )


def _b() -> SourceTable:
    return _table(
        STATEMENT_HEAD,
        "<tr><td>Expenses</td><td>400</td><td>450</td></tr>",
    )


def test_whitespace_and_page_furniture_between_tables_is_allowed() -> None:
    assert is_allowed_intervening_content("") is True
    assert is_allowed_intervening_content("   \n  ") is True
    assert is_allowed_intervening_content("<hr><page></page>__SEC_PAGE_X__") is True
    assert is_allowed_intervening_content("Note 13 (Continued)") is True


def test_substantial_prose_between_tables_is_rejected() -> None:
    assert is_allowed_intervening_content("Our revenue grew materially.") is False
    assert is_allowed_intervening_content("<p>a long narrative paragraph</p>") is False


def test_a_repeated_header_with_body_rows_is_a_continuation() -> None:
    decision = detect_table_continuation(_a(), _b())
    assert decision.is_continuation is True
    assert decision.header_rows_to_drop == 1
    assert "Matched 1 header row" in decision.reason


def test_a_table_with_no_repeated_header_is_not_a_continuation() -> None:
    other = _table(
        "<tr><th>Item</th><th>2019</th><th>2020</th></tr>",
        "<tr><td>Other</td><td>1</td><td>2</td></tr>",
    )
    assert detect_table_continuation(_a(), other).is_continuation is False


def test_a_single_row_table_is_never_a_continuation() -> None:
    single = _table("<tr><td>Signed</td><td>Date</td></tr>")
    decision = detect_table_continuation(single, single)
    assert decision.is_continuation is False
    assert "at least 2 rows" in decision.reason


def test_a_wildly_different_column_count_is_rejected() -> None:
    wide = _table(
        STATEMENT_HEAD,
        "<tr><td>a</td><td>1</td><td>2</td><td>3</td><td>4</td></tr>",
        "<tr><td>b</td><td>1</td><td>2</td><td>3</td><td>4</td></tr>",
    )
    decision = detect_table_continuation(_a(), wide)
    assert decision.is_continuation is False
    assert "Column count mismatch" in decision.reason


def test_a_one_column_difference_is_tolerated() -> None:
    wider = _table(
        STATEMENT_HEAD,
        "<tr><td>a</td><td>1</td><td>2</td><td>3</td></tr>",
        "<tr><td>b</td><td>1</td><td>2</td><td>3</td></tr>",
    )
    assert detect_table_continuation(_a(), wider).is_continuation is True


def test_prose_between_the_tables_blocks_continuation() -> None:
    decision = detect_table_continuation(
        _a(), _b(), intervening_html="A whole sentence."
    )
    assert decision.is_continuation is False
    assert decision.reason == "Substantial text between tables"


def test_a_header_only_second_table_is_not_a_continuation() -> None:
    header_only = _table(STATEMENT_HEAD)
    decision = detect_table_continuation(_a(), header_only)
    assert decision.is_continuation is False


def test_a_data_only_second_table_has_no_header_to_match() -> None:
    data_only = _table("<tr><td>Revenue</td><td>1,000</td><td>1,200</td></tr>")
    decision = detect_table_continuation(_a(), data_only)
    assert decision.is_continuation is False


def test_fusion_drops_the_repeated_header_and_concatenates_the_body_rows() -> None:
    a, b = _a(), _b()
    merged = fuse_source_tables(a, b, header_rows_to_drop=1)
    assert len(merged.rows) == len(a.rows) + len(b.rows) - 1
    assert merged.rows[0] == a.rows[0]
    assert merged.rows[1] == a.rows[1]
    assert [cell.text for cell in merged.rows[2]] == [cell.text for cell in b.rows[1]]


def test_fused_rows_are_reindexed_so_a_later_stage_can_address_them() -> None:
    third = _table("<tr><td>Net</td><td>600</td><td>750</td></tr>")
    merged = fuse_source_tables(fuse_source_tables(_a(), _b(), 1), third, 0)
    assert [[cell.row_index for cell in row] for row in merged.rows] == [
        [0, 0, 0],
        [1, 1, 1],
        [2, 2, 2],
        [3, 3, 3],
    ]


def test_fusion_preserves_the_first_tables_identity() -> None:
    a = _a()
    merged = fuse_source_tables(a, _b(), 1)
    assert merged.table_index == a.table_index
    assert merged.attributes == a.attributes
    assert merged.style == a.style


def test_continuation_markers_in_a_header_do_not_block_the_match() -> None:
    marked = _table(
        "<tr><th>Item</th><th>2017 (Continued)</th><th>2018</th></tr>",
        "<tr><td>Revenue</td><td>1,000</td><td>1,200</td></tr>",
    )
    plain = _table(
        "<tr><th>Item</th><th>2017</th><th>2018</th></tr>",
        "<tr><td>Revenue</td><td>1,000</td><td>1,200</td></tr>",
    )
    assert detect_table_continuation(plain, marked).is_continuation is True
