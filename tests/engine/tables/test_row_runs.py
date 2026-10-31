"""Generic geometric evidence for blank-separated ASCII table rows."""

from __future__ import annotations

from edgar_sec.engine.tables.row_runs import (
    find_table_row_runs,
    is_data_row_candidate,
    is_table_row_run_bridge,
    measure_row,
)

ROWS = (
    "Product A                  $100.00    Industrial units     Active",
    "Product B                  $200.00    Industrial units     Active",
    "Product C                  $300.00    Industrial units     Active",
)


def test_row_geometry_uses_whole_cells_and_generic_numeric_positions() -> None:
    row = measure_row(ROWS[0])
    assert row is not None
    assert len(row.field_starts) == 4
    assert row.numeric_fields == (1,)
    assert row.field_kinds == (
        "alphabetic",
        "numeric",
        "alphabetic",
        "alphabetic",
    )


def test_three_blank_separated_compatible_rows_form_a_run() -> None:
    blocks = [
        (0, 1, (ROWS[0],)),
        (2, 3, (ROWS[1],)),
        (4, 5, (ROWS[2],)),
    ]
    runs = find_table_row_runs(blocks, {0, 1, 2})
    assert len(runs) == 1
    assert runs[0].first_block == 0
    assert runs[0].after_last_block == 3
    assert runs[0].start_line == 0
    assert runs[0].end_line == 5
    assert runs[0].row_count == 3


def test_two_compatible_rows_are_below_the_promotion_minimum() -> None:
    blocks = [(0, 1, (ROWS[0],)), (2, 3, (ROWS[1],))]
    assert find_table_row_runs(blocks, {0, 1}) == ()


def test_repeated_numeric_columns_promote_for_schedules_and_indexes() -> None:
    schedule = (
        "Net sales                    $1,234.00",
        "Cost of sales                  987.00",
        "Gross profit                   247.00",
    )
    index = (
        "Balance sheets                     13",
        "Statements of operations            14",
        "Cash flows                           15",
    )
    section_index = (
        "1                    Risk factors       13",
        "2                    Properties        16",
        "3                    Legal matters     19",
    )
    schedule_blocks = [(i * 2, i * 2 + 1, (line,)) for i, line in enumerate(schedule)]
    index_blocks = [(i * 2, i * 2 + 1, (line,)) for i, line in enumerate(index)]
    section_blocks = [
        (i * 2, i * 2 + 1, (line,)) for i, line in enumerate(section_index)
    ]

    assert len(find_table_row_runs(schedule_blocks, {0, 1, 2})) == 1
    assert len(find_table_row_runs(index_blocks, {0, 1, 2})) == 1
    assert len(find_table_row_runs(section_blocks, {0, 1, 2})) == 1


def test_packed_multi_numeric_rows_form_one_run_inside_a_block() -> None:
    packed = (
        "Current assets                 100        90         80",
        "Property and equipment          200       180        160",
        "Total assets                     300       270        240",
    )
    blocks = [(0, 3, packed)]

    runs = find_table_row_runs(blocks, {0})

    assert len(runs) == 1
    assert runs[0].row_count == 3
    assert runs[0].start_line == 0
    assert runs[0].end_line == 3


def test_numeric_column_drift_does_not_truncate_a_packed_run() -> None:
    rows = (
        "Second Quarter                 $0.85       $0.39",
        "Third Quarter                  $0.90       $0.42",
        "First Quarter--  2000          $0.97       $0.53",
        "Fourth Quarter                 $1.02       $0.57",
    )
    runs = find_table_row_runs([(0, len(rows), rows)], {0})

    assert len(runs) == 1
    assert runs[0].row_count == 4
    assert runs[0].end_line == 4


def test_placeholder_columns_keep_a_ragged_tail_inside_the_run() -> None:
    rows = (
        "Balance, November 30, 1991....  6,659,000     8,260       352,000      6,337",
        "Incentive shares issued.......        --         (2)           --         (2)",
        "Balance, November 30, 1992....  6,659,000     8,258       352,000      6,335",
        "Shares issued in private ",
        "  placement...................  1,283,000    11,485            --         --",
        "Shares purchased..............         --        --         7,000         81",
        "Stock options exercised.......         --      (149)      (15,000)      (265)",
        "Redemption of preferred stock.         --        --      (132,000)    (2,368)",
        "Employee termination benefits.         --        --       (21,000)      (380)",
        "Balance, November 30, 1993....  7,942,000   $19,594       191,000     $3,403",
    )
    blocks = [
        (0, 1, (rows[0],)),
        (2, 3, (rows[1],)),
        (4, 5, (rows[2],)),
        (6, 12, rows[3:9]),
        (13, 14, (rows[9],)),
    ]

    runs = find_table_row_runs(blocks, set(range(len(blocks))))

    assert len(runs) == 1
    assert runs[0].row_count == 9
    assert runs[0].end_line == 14


def test_non_numeric_continuation_stays_inside_a_confirmed_run() -> None:
    lines = (
        "Jane Smith       51       Chief Executive Officer",
        "  and Director",
        "John Jones       48       Chief Financial Officer",
        "Mary Brown       55       Treasurer",
    )
    runs = find_table_row_runs([(0, len(lines), lines)], {0})

    assert len(runs) == 1
    assert runs[0].row_count == 3
    assert runs[0].start_line == 0
    assert runs[0].end_line == 4


def test_generic_roster_rows_with_an_internal_numeric_field_form_a_run() -> None:
    roster = (
        "Jordan Lee                   48    President and Director",
        "Casey Morgan                 52    Chief Financial Officer",
        "Taylor Kim                   44    Vice President, Operations",
    )
    blocks = [(index * 2, index * 2 + 1, (line,)) for index, line in enumerate(roster)]

    runs = find_table_row_runs(blocks, {0, 1, 2})

    assert len(runs) == 1
    assert runs[0].row_count == 3


def test_a_gap_of_more_than_one_blank_line_breaks_a_run() -> None:
    blocks = [
        (0, 1, (ROWS[0],)),
        (3, 4, (ROWS[1],)),
        (6, 7, (ROWS[2],)),
    ]
    assert find_table_row_runs(blocks, {0, 1, 2}) == ()


def test_prose_shaped_aligned_lines_are_not_promoted() -> None:
    prose = (
        "Revenue increased by         20%       after the acquisition.",
        "Costs declined by            10%       during the following year.",
        "Margins improved by           5%       compared with the prior period.",
    )
    blocks = [(index * 2, index * 2 + 1, (line,)) for index, line in enumerate(prose)]
    assert find_table_row_runs(blocks, {0, 1, 2}) == ()


def test_bullet_markers_alone_do_not_supply_numeric_row_evidence() -> None:
    bullets = (
        "*    Online services             Work-at-home schemes",
        "*    Pyramid schemes             Books and magazines",
        "*    Business opportunities     Subscriptions",
    )
    assert all(measure_row(line) is not None for line in bullets)
    blocks = [(index * 2, index * 2 + 1, (line,)) for index, line in enumerate(bullets)]
    assert find_table_row_runs(blocks, {0, 1, 2}) == ()


def test_semicolon_terminated_numbered_prose_is_not_promoted() -> None:
    prose = (
        "3.      The officer prepares and reviews the annual financial statements;",
        "4.      The officer evaluates the controls and delivers a report to the board;",
        "5.      The officer reports changes and any weaknesses identified during review;",
    )
    blocks = [(index * 2, index * 2 + 1, (line,)) for index, line in enumerate(prose)]
    assert find_table_row_runs(blocks, {0, 1, 2}) == ()


def test_wrapped_cell_continuation_stays_with_its_row() -> None:
    first = "Product A                  $100.00    Industrial units     $8,000 pending,"
    wrapped = (first, " " * 60 + "$2,000 posted", " " * 60 + "to inventory")
    blocks = [
        (0, 1, (ROWS[0],)),
        (2, 3, (ROWS[1],)),
        (4, 7, wrapped),
    ]
    runs = find_table_row_runs(blocks, {0, 1, 2})
    assert len(runs) == 1
    assert runs[0].row_count == 3
    assert runs[0].end_line == 7


def test_placeholder_cells_do_not_break_a_repeated_numeric_column() -> None:
    lines = (
        "Service A                 100        90",
        "Service B                   -         -",
        "Service C                 300       280",
    )
    blocks = [(index * 2, index * 2 + 1, (line,)) for index, line in enumerate(lines)]
    assert find_table_row_runs(blocks, {0, 1, 2})[0].row_count == 3


def test_data_row_shape_is_not_confused_with_a_period_header() -> None:
    assert is_data_row_candidate((ROWS[0],))
    assert not is_data_row_candidate(("Description              2024       2023",))


def test_non_numeric_justified_lines_have_no_row_geometry() -> None:
    assert (
        measure_row("The company             conducts business     worldwide") is None
    )


def test_a_numeric_subtotal_and_year_label_can_bridge_confirmed_runs() -> None:
    lines = (
        "Sub-total 2000           $600.00",
        "--------------           ---------",
        "2001",
    )
    assert is_table_row_run_bridge(lines)
    assert not is_table_row_run_bridge(("The following table provides an overview:",))


def test_dot_leader_rows_with_repeated_page_columns_form_a_run() -> None:
    schedule = "2002                       $1,686"
    toc_rows = (
        "Consolidated statements............    16",
        "Statements of operations...........    17",
        "Statements of cash flows...........    18",
    )
    assert measure_row(schedule) is not None
    blocks = [
        (index * 2, index * 2 + 1, (line,)) for index, line in enumerate(toc_rows)
    ]
    assert len(find_table_row_runs(blocks, {0, 1, 2})) == 1
