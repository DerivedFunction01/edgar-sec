"""Separating a table’s narrative from its grid, and rejoining an interrupted one.
Both are conservative in one direction: an unrecognised cue leaves the narrative
inside the table, while a false cue strips a financial line out of its table.
"""

from __future__ import annotations

from edgar_sec.engine.reflow.types import (
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    SpanDecision,
)
from edgar_sec.engine.tables.policy.intro import (
    is_tableish_block,
    split_structural_table_intro,
    unify_table_prose,
)
from edgar_sec.engine.tables.protection.tags import SENTINEL_PREFIX

TABLE_LINES = (
    "Name                  2024       2023",
    "Alpha                 10         9",
)


def test_a_cue_line_before_grid_geometry_is_split_out() -> None:
    intro = "The following information is presented below"
    narrative, table_lines = split_structural_table_intro((intro, *TABLE_LINES))
    assert narrative == (intro,)
    assert table_lines == TABLE_LINES


def test_a_sentence_terminated_cue_is_also_split_out() -> None:
    intro = "The following table summarizes our results."
    narrative, table_lines = split_structural_table_intro((intro, *TABLE_LINES))
    assert narrative == (intro,)
    assert table_lines == TABLE_LINES


def test_filing_specific_prose_is_not_a_cue() -> None:
    lines = ("The fair value was estimated using assumptions", *TABLE_LINES)
    assert split_structural_table_intro(lines) == ((), lines)


def test_a_block_that_does_not_start_with_a_cue_is_returned_whole() -> None:
    lines = (
        "Revenue by segment       2024       2023",
        "  Automotive             $1,200     $1,100",
    )
    assert split_structural_table_intro(lines) == ((), lines)


def test_a_cue_with_no_geometry_after_it_is_returned_whole() -> None:
    lines = ("The following table summarizes our results.",)
    assert split_structural_table_intro(lines) == ((), lines)


def test_a_blank_block_is_returned_whole() -> None:
    lines = ("", "   ")
    assert split_structural_table_intro(lines) == ((), lines)


def test_a_tab_indented_cue_column_is_split_out() -> None:
    lines = ("This sentence introduces nothing at all.", "\tCol A\t1", "\tCol B\t2")
    narrative, table_lines = split_structural_table_intro(lines)
    assert narrative == ("This sentence introduces nothing at all.",)
    assert table_lines == ("\tCol A\t1", "\tCol B\t2")


def test_a_multiline_wrapped_cue_is_split_out() -> None:
    intro = (
        "Aggregate annual maturities of notes payable and long-term debt",
        "are as follows:",
    )
    narrative, table_lines = split_structural_table_intro((*intro, *TABLE_LINES))
    assert narrative == intro
    assert table_lines == TABLE_LINES


def test_cue_stops_at_colon_leaving_indented_headers() -> None:
    lines = (
        "Debt obligations are as follows:",
        "                                                       December 31,",
        "                                                    1999         1998",
        "Mortgage loan, interest accrues at 11 1/2%,     $3,811,828   $3,811,828",
    )
    narrative, table_lines = split_structural_table_intro(lines)
    assert narrative == ("Debt obligations are as follows:",)
    assert table_lines == lines[1:]


class _Features:
    """A stand-in for the geometry record, holding only what the policy reads."""

    def __init__(self, **overrides: object) -> None:
        self.gap_start_rows: tuple = ()
        self.has_tab = False
        self.shared_numeric_columns = 0
        self.has_separator = False
        self.numeric_cell_rows: tuple = ()
        for name, value in overrides.items():
            setattr(self, name, value)


def test_a_block_with_no_layout_is_not_tableish() -> None:
    assert is_tableish_block(_Features()) is False


def test_three_numeric_rows_with_gaps_and_shared_columns_are_tableish() -> None:
    features = _Features(
        gap_start_rows=((4,), (4,), (4,)),
        numeric_cell_rows=((8,), (8,), (8,)),
        shared_numeric_columns=2,
    )
    assert is_tableish_block(features) is True


def test_a_separator_with_two_numeric_rows_is_tableish() -> None:
    features = _Features(
        gap_start_rows=((4,), (4,)),
        has_separator=True,
        numeric_cell_rows=((8,), (8,)),
    )
    assert is_tableish_block(features) is True


def test_a_tab_plus_a_separator_is_tableish() -> None:
    features = _Features(has_tab=True, has_separator=True, numeric_cell_rows=((8,),))
    assert is_tableish_block(features) is True


def test_a_tab_alone_is_not_tableish() -> None:
    assert is_tableish_block(_Features(has_tab=True)) is False


def test_two_numeric_rows_without_enough_gaps_is_not_tableish() -> None:
    features = _Features(
        gap_start_rows=((4,), (4,)),
        numeric_cell_rows=((8,), (8,)),
    )
    assert is_tableish_block(features) is False


def test_a_single_gap_row_with_no_numeric_cells_is_not_tableish() -> None:
    features = _Features(gap_start_rows=((4,),))
    assert is_tableish_block(features) is False


PROSE_BEFORE = (
    "The following table summarizes revenue for the",
    "years ended December 31, 2024 and 2023:",
)
PROSE_AFTER = (
    "and shows strong growth across all segments.",
    "A second sentence follows.",
)
TABLE_BLOCK = (
    "Revenue by segment       2024       2023",
    "  Automotive             $1,200     $1,100",
)


def _decisions() -> list[SpanDecision]:
    return [
        SpanDecision(ACTION_UNWRAP, 0, 2, 0.7, ("ordinary_prose",), "fast_prose"),
        SpanDecision(
            ACTION_TAG_AND_PRESERVE,
            2,
            4,
            0.8,
            ("inferred_table_layout",),
            "table_continuity",
        ),
        SpanDecision(ACTION_UNWRAP, 4, 6, 0.7, ("ordinary_prose",), "fast_prose"),
    ]


def _blocks() -> list[tuple[int, int, tuple[str, ...]]]:
    return [(0, 2, PROSE_BEFORE), (2, 4, TABLE_BLOCK), (4, 6, PROSE_AFTER)]


def _unify(decisions: list[SpanDecision], index: int, blocks=None) -> object:
    return unify_table_prose(
        decisions,
        blocks if blocks is not None else _blocks(),
        index,
        set(),
        [_blocks()[index]],
    )


def test_prose_interrupted_by_a_table_is_reunited() -> None:
    unified = _unify(_decisions(), 1)
    assert unified == (*PROSE_BEFORE, *PROSE_AFTER)


def test_long_prose_decisions_are_not_collapsed_around_a_table() -> None:
    blocks = [
        (
            0,
            5,
            (
                "A long paragraph begins here",
                "and carries several further lines",
                "with context and figures",
                "before introducing a grid:",
            ),
        ),
        (5, 7, TABLE_BLOCK),
        (7, 9, ("and a continuation follows.",)),
    ]
    decisions = [
        SpanDecision(ACTION_UNWRAP, 0, 5, 0.7, ("ordinary_prose",), "fast_prose"),
        SpanDecision(
            ACTION_TAG_AND_PRESERVE,
            5,
            7,
            0.8,
            ("repeated_row_geometry",),
            "table_row_run",
        ),
        SpanDecision(ACTION_UNWRAP, 7, 9, 0.7, ("ordinary_prose",), "fast_prose"),
    ]
    assert unify_table_prose(decisions, blocks, 1, set(), [blocks[1]]) is None


def test_a_capitalized_continuation_is_not_reunited() -> None:
    blocks = [
        (0, 2, ("A sentence that already ends here.", "Another one.")),
        (2, 4, TABLE_BLOCK),
        (4, 6, ("And this starts capitalized.", "A second sentence follows.")),
    ]
    assert _unify(_decisions(), 1, blocks) is None


def test_a_negative_boundary_phrase_is_not_reunited() -> None:
    blocks = [
        (0, 2, PROSE_BEFORE),
        (2, 4, TABLE_BLOCK),
        (
            4,
            6,
            (
                "item 7. The plan of acquisition is attached.",
                "A second sentence follows.",
            ),
        ),
    ]
    assert _unify(_decisions(), 1, blocks) is None


def test_an_article_is_a_legitimate_continuation() -> None:
    blocks = [
        (0, 2, PROSE_BEFORE),
        (2, 4, TABLE_BLOCK),
        (4, 6, ("a single letter token starts this.", "A second sentence follows.")),
    ]
    assert _unify(_decisions(), 1, blocks) is not None


def test_a_bare_letter_continuation_is_not_reunited() -> None:
    blocks = [
        (0, 2, PROSE_BEFORE),
        (2, 4, TABLE_BLOCK),
        (
            4,
            6,
            ("I continued after the table ends here.", "A second sentence follows."),
        ),
    ]
    assert _unify(_decisions(), 1, blocks) is None


def test_the_first_and_last_blocks_are_never_reunited() -> None:
    assert _unify(_decisions(), 0) is None
    assert _unify(_decisions(), 2) is None


def test_a_prose_block_next_to_another_prose_block_is_not_reunited() -> None:
    decisions = [
        SpanDecision(ACTION_UNWRAP, 0, 2, 0.7, (), "fast_prose"),
        SpanDecision(ACTION_UNWRAP, 2, 4, 0.7, (), "fast_prose"),
        SpanDecision(ACTION_UNWRAP, 4, 6, 0.7, (), "fast_prose"),
    ]
    assert _unify(decisions, 1) is None


def test_a_skipped_neighbour_is_not_reunited() -> None:
    assert (
        unify_table_prose(_decisions(), _blocks(), 1, {2}, [(2, 4, TABLE_BLOCK)])
        is None
    )


def test_a_protected_table_adjacent_to_the_block_blocks_reuniting() -> None:
    blocks = [
        (0, 2, (f"{SENTINEL_PREFIX}0__",)),
        (2, 4, TABLE_BLOCK),
        (4, 6, PROSE_AFTER),
    ]
    assert _unify(_decisions(), 1, blocks) is None


def test_an_empty_neighbouring_block_blocks_reuniting() -> None:
    blocks = [
        (0, 2, PROSE_BEFORE),
        (2, 4, TABLE_BLOCK),
        (4, 6, ("", "   ")),
    ]
    assert _unify(_decisions(), 1, blocks) is None


def test_a_tagged_block_adjacent_to_another_tag_is_not_reunited() -> None:
    decisions = [
        SpanDecision(ACTION_TAG_AND_PRESERVE, 0, 2, 0.8, (), "table"),
        SpanDecision(ACTION_TAG_AND_PRESERVE, 2, 4, 0.8, (), "table"),
        SpanDecision(ACTION_UNWRAP, 4, 6, 0.7, (), "fast_prose"),
    ]
    assert _unify(decisions, 1) is None


def test_a_preserved_block_is_still_a_unification_candidate() -> None:
    decisions = [
        SpanDecision(ACTION_PRESERVE, 0, 2, 1.0, (), "hard_preserve"),
        SpanDecision(
            ACTION_TAG_AND_PRESERVE, 2, 4, 0.8, ("inferred_table_layout",), "table"
        ),
        SpanDecision(ACTION_UNWRAP, 4, 6, 0.7, (), "fast_prose"),
    ]
    assert _unify(decisions, 1) is not None
