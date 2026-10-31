"""Recognizing a wrapped table row’s continuation lines.
A wrapped description carries no numeric cells of its own, so the signal is
positional: its numbers sit under the columns earlier rows established.
"""

from __future__ import annotations

from edgar_sec.engine.reflow.types import ReflowPolicy
from edgar_sec.engine.tables.policy.continuation import is_table_row_continuation

PREVIOUS = ("Product A                100        90",)
PAGE_BOUNDARY_POLICY = ReflowPolicy(
    is_page_boundary_line=lambda line: line.strip() == "<PAGE> 1"
)


def test_empty_blocks_are_not_a_continuation() -> None:
    assert not is_table_row_continuation((), ())
    assert not is_table_row_continuation(PREVIOUS, ())
    assert not is_table_row_continuation((), PREVIOUS)


def test_a_blank_continuation_is_not_a_continuation() -> None:
    assert not is_table_row_continuation(PREVIOUS, ("", "   "))


def test_a_numeric_bridge_needs_two_aligned_cells() -> None:
    one_aligned_cell = ("Narrative                  300",)
    two_aligned_cells = ("Product B                200        180",)
    assert not is_table_row_continuation(PREVIOUS, one_aligned_cell)
    assert is_table_row_continuation(PREVIOUS, two_aligned_cells)


def test_an_all_separator_continuation_is_always_a_continuation() -> None:
    assert is_table_row_continuation(PREVIOUS, ("-------   ------",))
    assert is_table_row_continuation(PREVIOUS, ("-------   ------", "=========="))


def test_a_single_aligned_cell_needs_a_total_or_numeric_remainder() -> None:
    # "Total" at column 7 aligns with nothing, so the keyword fallback is the only carrier.
    misaligned_total = ("Total  200",)
    aligned_total = ("Total                    200        180",)
    not_aligned = (
        "The quick brown fox jumped over the lazy dog and then some more text.",
    )
    assert not is_table_row_continuation(PREVIOUS, misaligned_total)
    assert is_table_row_continuation(PREVIOUS, aligned_total)
    assert not is_table_row_continuation(PREVIOUS, not_aligned)


def test_a_long_aligned_block_is_not_a_continuation() -> None:
    aligned = ("Total  200", "Net  190", "Gross  10")
    assert not is_table_row_continuation(PREVIOUS, aligned)


def test_a_prose_line_with_one_aligned_cell_is_not_a_continuation() -> None:
    # The single-cell path demands every word be numeric or a total keyword, so any
    # prose word refuses regardless of the sentence check in the same loop.
    assert not is_table_row_continuation(
        PREVIOUS, ("Revenue grew by a margin.                    190",)
    )


def test_two_sentence_shaped_lines_do_not_become_a_continuation_by_alignment() -> None:
    aligned = ("Total revenue grew.  Net  190", "Net grew too.  Gross  10")
    assert not is_table_row_continuation(PREVIOUS, aligned)


def test_numeric_row_and_unaligned_prose_in_one_block_are_not_a_continuation() -> None:
    block = (
        "Total                                     $ 480,415         $ 462,856",
        "      At December 31, 1999, the company had approximately $93,624,000",
    )
    previous = (
        "United States                              $ 331,765         $ 323,458",
        "Argentina                                    111,486           103,968",
        "All other                                     37,164            35,430",
    )
    assert not is_table_row_continuation(previous, block)


def test_a_column_aligned_continuation_line_after_a_row_is_kept() -> None:
    previous = ("Product A                100        90",)
    wrapped = ("Product B                200        180", " " * 25 + "continued cell")
    assert is_table_row_continuation(previous, wrapped)


def test_a_page_boundary_line_is_refused_under_the_policy() -> None:
    assert not is_table_row_continuation(
        PREVIOUS,
        ("<PAGE> 1", "Product B                200        180"),
        PAGE_BOUNDARY_POLICY,
    )
    # Without the policy the same block is read on geometry alone.
    assert is_table_row_continuation(
        PREVIOUS, ("<PAGE> 1", "Product B                200        180")
    )


def test_no_columns_established_means_no_continuation() -> None:
    assert not is_table_row_continuation(
        ("A line of ordinary prose", "Another line of ordinary prose"),
        ("Product B                200        180",),
    )


def test_the_policy_is_optional() -> None:
    assert is_table_row_continuation(
        PREVIOUS, ("Product B                200        180",), None
    )
    assert is_table_row_continuation(
        PREVIOUS, ("Product B                200        180",)
    )
