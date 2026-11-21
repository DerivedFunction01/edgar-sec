"""Table boundary resolution: growing a seed outward, then holding it to discipline.
Each case pins one absorbable signal or one refusal, so a rule that absorbs too
eagerly shows up as a table that swallowed the page footer.
"""

from __future__ import annotations

from edgar_sec.domain.taxonomy.statements.predicates import (
    is_financial_table_bridge_line,
    is_financial_table_tail_line,
)
from edgar_sec.engine.reflow.types import (
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    ReflowPolicy,
    SpanDecision,
)
from edgar_sec.engine.tables.protection.tags import SENTINEL_PREFIX
from edgar_sec.engine.tables.resolver import resolve_table_regions
from edgar_sec.engine.tables.structural import is_header_prefix

PRODUCTION_POLICY = ReflowPolicy(
    is_page_boundary_line=lambda line: line.strip() in {"<PAGE> 1", "<page>F-1"},
    is_table_bridge_line=is_financial_table_bridge_line,
    is_table_tail_line=is_financial_table_tail_line,
)

BLOCKS: list[tuple[int, int, tuple[str, ...]]] = [
    (
        0,
        2,
        (
            "Description                         2024       2023",
            "Cash                         100        90",
        ),
    ),
    (
        3,
        7,
        (
            "Automotive               $1,200     $1,100",
            "Industrial               $2,050     $1,980",
            "Total                    $3,250     $3,080",
            "",
        ),
    ),
    (
        8,
        11,
        (
            "LIABILITIES AND STOCKHOLDERS' EQUITY",
            "",
            "Total liabilities         100        90",
        ),
    ),
]


def _decision(action: str, start: int, end: int, *evidence: str) -> SpanDecision:
    return SpanDecision(action, start, end, 0.8, evidence, "table_continuity")


def test_no_decisions_resolves_to_no_decisions() -> None:
    assert resolve_table_regions([], BLOCKS) == []


def test_a_single_seed_is_returned_unchanged() -> None:
    decision = _decision(ACTION_TAG_AND_PRESERVE, 0, 2, "repeated_numeric_columns:1")
    assert resolve_table_regions([decision], BLOCKS) == [decision]


def test_a_preserve_decision_passes_through_untouched() -> None:
    decision = _decision(ACTION_PRESERVE, 0, 2, "header")
    assert resolve_table_regions([decision], BLOCKS) == [decision]


def test_a_seed_expands_upward_to_absorb_a_header_prefix() -> None:
    decisions = [
        _decision(ACTION_PRESERVE, 0, 2, "header"),
        _decision(ACTION_TAG_AND_PRESERVE, 3, 7, "repeated_numeric_columns:2"),
    ]
    resolved = resolve_table_regions(decisions, BLOCKS)
    assert len(resolved) == 1
    assert resolved[0].start_line == 0
    assert resolved[0].end_line == 7
    assert "expanded_table_header" in resolved[0].evidence


def test_row_run_seed_does_not_absorb_an_unaligned_signature_as_a_header() -> None:
    signature = (
        "By: /s/Officer",
        "     -------------------",
        "     Officer Name",
        "     Principal Executive Officer",
        "     October 25, 2002",
    )
    assert is_header_prefix(signature)
    blocks = [
        (0, 5, signature),
        (6, 7, ("Item A                  $100.00    Service group     Active",)),
        (8, 9, ("Item B                  $200.00    Service group     Active",)),
        (10, 11, ("Item C                  $300.00    Service group     Active",)),
    ]
    decisions = [
        _decision(ACTION_PRESERVE, 0, 5, "signature_shape"),
        _decision(
            ACTION_TAG_AND_PRESERVE,
            6,
            11,
            "repeated_row_geometry",
            "repeated_numeric_field",
        ),
    ]

    resolved = resolve_table_regions(decisions, blocks)

    assert [decision.action for decision in resolved] == [
        ACTION_PRESERVE,
        ACTION_TAG_AND_PRESERVE,
    ]
    assert resolved[0].start_line == 0
    assert resolved[1].start_line == 6


def test_a_header_too_far_away_is_not_absorbed() -> None:
    far_blocks: list[tuple[int, int, tuple[str, ...]]] = [
        (0, 1, ("CONSOLIDATED BALANCE SHEETS",)),
        (
            10,
            12,
            ("Cash                         100        90", "Other        90        80"),
        ),
    ]
    decisions = [
        _decision(ACTION_PRESERVE, 0, 1, "header"),
        _decision(ACTION_TAG_AND_PRESERVE, 10, 12, "repeated_numeric_columns:1"),
    ]
    resolved = resolve_table_regions(decisions, far_blocks)
    assert [d.start_line for d in resolved] == [0, 10]


def test_a_header_containing_a_protected_table_is_not_absorbed() -> None:
    blocks: list[tuple[int, int, tuple[str, ...]]] = [
        (0, 2, ("CONSOLIDATED BALANCE SHEETS", f"{SENTINEL_PREFIX}0__")),
        (
            3,
            5,
            ("Cash                         100        90", "Other        90        80"),
        ),
    ]
    decisions = [
        _decision(ACTION_PRESERVE, 0, 2, "header"),
        _decision(ACTION_TAG_AND_PRESERVE, 3, 5, "repeated_numeric_columns:1"),
    ]
    resolved = resolve_table_regions(decisions, blocks)
    assert [d.start_line for d in resolved] == [0, 3]


def test_a_grown_span_overlapping_a_protected_table_is_downgraded() -> None:
    blocks: list[tuple[int, int, tuple[str, ...]]] = [
        (0, 1, (f"{SENTINEL_PREFIX}0__",))
    ]
    resolved = resolve_table_regions(
        [_decision(ACTION_TAG_AND_PRESERVE, 0, 1, "inferred_table_layout")], blocks
    )
    assert resolved == [
        SpanDecision(
            ACTION_PRESERVE,
            0,
            1,
            0.8,
            ("inferred_table_layout", "protected_table_overlap"),
            "table_continuity",
        )
    ]


def test_a_span_without_numeric_evidence_is_downgraded() -> None:
    blocks: list[tuple[int, int, tuple[str, ...]]] = [
        (0, 2, ("just some words on a line", "and more words on another line")),
    ]
    resolved = resolve_table_regions(
        [_decision(ACTION_TAG_AND_PRESERVE, 0, 2, "inferred_table_layout")], blocks
    )
    assert resolved[0].action == ACTION_PRESERVE
    assert "tag_discipline_downgrade" in resolved[0].evidence


def test_a_gap_of_more_than_one_blank_line_stops_the_sweep() -> None:
    blocks: list[tuple[int, int, tuple[str, ...]]] = [
        (0, 2, ("Revenue       2024", "  A       $1,000")),
        (5, 7, ("Revenue       2024", "  B         $500")),
    ]
    decisions = [
        _decision(ACTION_TAG_AND_PRESERVE, 0, 2, "repeated_numeric_columns:1"),
        _decision(ACTION_TAG_AND_PRESERVE, 5, 7, "repeated_numeric_columns:1"),
    ]
    assert len(resolve_table_regions(decisions, blocks)) == 2


def test_one_blank_line_bridges_two_adjacent_tables() -> None:
    blocks: list[tuple[int, int, tuple[str, ...]]] = [
        (0, 2, ("Revenue       2024", "  A       $1,000")),
        (2, 3, ("",)),
        (3, 5, ("Revenue       2024", "  B         $500")),
    ]
    decisions = [
        _decision(ACTION_TAG_AND_PRESERVE, 0, 2, "repeated_numeric_columns:1"),
        _decision(ACTION_TAG_AND_PRESERVE, 3, 5, "repeated_numeric_columns:1"),
    ]
    resolved = resolve_table_regions(decisions, blocks)
    assert len(resolved) == 1
    assert resolved[0].end_line == 5
    assert "bridged_blank_line" in resolved[0].evidence


def test_a_wrapped_continuation_row_is_absorbed() -> None:
    blocks: list[tuple[int, int, tuple[str, ...]]] = [
        (
            0,
            2,
            (
                "Total assets                 300       270",
                "Other assets                 200       180",
            ),
        ),
        (2, 4, ("LIABILITIES AND STOCKHOLDERS' EQUITY", "")),
        (
            4,
            6,
            (
                "Current liabilities           50        45",
                "Long-term debt                50        45",
            ),
        ),
        (6, 7, ("==========  ==========",)),
        (
            7,
            9,
            (
                "A narrative paragraph that follows the statement in",
                "ordinary prose across two wrapped lines",
            ),
        ),
    ]
    decisions = [
        _decision(ACTION_TAG_AND_PRESERVE, 0, 2, "seed"),
        _decision(ACTION_PRESERVE, 2, 4, "bridge"),
        _decision(ACTION_TAG_AND_PRESERVE, 4, 6, "body"),
        _decision(ACTION_PRESERVE, 6, 7, "divider"),
        _decision(ACTION_UNWRAP, 7, 9, "prose"),
    ]
    resolved = resolve_table_regions(decisions, blocks, PRODUCTION_POLICY)
    assert [d.action for d in resolved] == [ACTION_TAG_AND_PRESERVE, ACTION_UNWRAP]
    assert resolved[0].end_line == 7
    assert "bridged_structural_section" in resolved[0].evidence
    assert "extended_multiline_rows" in resolved[0].evidence


def test_a_structural_tail_after_the_bridged_table_is_included() -> None:
    blocks: list[tuple[int, int, tuple[str, ...]]] = [
        (
            0,
            2,
            (
                "Total assets                 300       270",
                "Other assets                 200       180",
            ),
        ),
        (2, 4, ("LIABILITIES AND STOCKHOLDERS' EQUITY", "")),
        (4, 5, ("Current liabilities           50        45",)),
        (5, 6, ("Total liabilities and stockholders' deficit  100  90",)),
        (
            6,
            8,
            (
                "A narrative paragraph that follows the statement in",
                "ordinary prose across two wrapped lines",
            ),
        ),
    ]
    decisions = [
        _decision(ACTION_TAG_AND_PRESERVE, 0, 2, "seed"),
        _decision(ACTION_PRESERVE, 2, 4, "bridge"),
        _decision(ACTION_TAG_AND_PRESERVE, 4, 5, "body"),
        _decision(ACTION_PRESERVE, 5, 6, "tail"),
        _decision(ACTION_UNWRAP, 6, 8, "prose"),
    ]
    resolved = resolve_table_regions(decisions, blocks, PRODUCTION_POLICY)
    assert [d.action for d in resolved] == [ACTION_TAG_AND_PRESERVE, ACTION_UNWRAP]
    assert resolved[0].end_line == 6
    assert "included_table_tail" in resolved[0].evidence


def test_prose_between_two_tables_is_not_absorbed() -> None:
    first_table = (
        "Product A                100        90",
        "Product A2               110        95",
    )
    prose = (
        "This paragraph explains the service terms and the calculation method.",
        "It contains narrative context that is not a row of the table.",
    )
    second_table = (
        "Product C                300        250",
        "Product C2               310        260",
    )
    blocks: list[tuple[int, int, tuple[str, ...]]] = [
        (0, 2, first_table),
        (2, 4, prose),
        (5, 7, second_table),
    ]
    decisions = [
        _decision(ACTION_TAG_AND_PRESERVE, 0, 2, "repeated_numeric_columns:1"),
        _decision(ACTION_UNWRAP, 2, 5, "ordinary_prose"),
        _decision(ACTION_TAG_AND_PRESERVE, 5, 7, "repeated_numeric_columns:1"),
    ]
    assert resolve_table_regions(decisions, blocks, PRODUCTION_POLICY) == decisions


def test_a_numeric_candidate_stops_the_sweep() -> None:
    blocks: list[tuple[int, int, tuple[str, ...]]] = [
        (0, 2, ("Revenue       2024", "  A       $1,000")),
        (2, 3, ("Narrative                  300",)),
    ]
    decisions = [
        _decision(ACTION_TAG_AND_PRESERVE, 0, 2, "repeated_numeric_columns:1"),
        _decision(ACTION_PRESERVE, 2, 3, "next"),
    ]
    resolved = resolve_table_regions(decisions, blocks, PRODUCTION_POLICY)
    assert len(resolved) == 2


def test_a_page_marker_between_two_tables_bridges_them() -> None:
    blocks: list[tuple[int, int, tuple[str, ...]]] = [
        (0, 1, ("Product A                100        90",)),
        (1, 2, ("<PAGE> 1",)),
        (2, 3, ("Product C                300        250",)),
    ]
    decisions = [
        _decision(ACTION_TAG_AND_PRESERVE, 0, 1, "repeated_numeric_columns:1"),
        _decision(ACTION_PRESERVE, 1, 2, "page_marker"),
        _decision(ACTION_TAG_AND_PRESERVE, 2, 3, "repeated_numeric_columns:1"),
    ]
    resolved = resolve_table_regions(decisions, blocks, PRODUCTION_POLICY)
    assert len(resolved) == 1
    assert resolved[0].end_line == 3
    assert "bridged_page_marker" in resolved[0].evidence


def test_a_page_marker_with_no_following_table_does_not_bridge() -> None:
    blocks: list[tuple[int, int, tuple[str, ...]]] = [
        (0, 1, ("Product A                100        90",)),
        (1, 2, ("<PAGE> 1",)),
    ]
    decisions = [
        _decision(ACTION_TAG_AND_PRESERVE, 0, 1, "repeated_numeric_columns:1"),
        _decision(ACTION_PRESERVE, 1, 2, "page_marker"),
    ]
    resolved = resolve_table_regions(decisions, blocks, PRODUCTION_POLICY)
    assert len(resolved) == 2


def test_a_wider_max_blank_lines_still_bridges_adjacent_tables() -> None:
    blocks: list[tuple[int, int, tuple[str, ...]]] = [
        (0, 1, ("Product A                100        90",)),
        (1, 3, ("Revenue       2024", "  B         $500")),
    ]
    decisions = [
        _decision(ACTION_TAG_AND_PRESERVE, 0, 1, "repeated_numeric_columns:1"),
        _decision(ACTION_TAG_AND_PRESERVE, 3, 4, "repeated_numeric_columns:1"),
    ]
    resolved = resolve_table_regions(decisions, blocks, max_blank_lines=2)
    assert len(resolved) == 1


def test_resolution_is_a_fixed_point() -> None:
    decisions = [
        _decision(ACTION_PRESERVE, 0, 2, "header"),
        _decision(ACTION_TAG_AND_PRESERVE, 3, 7, "repeated_numeric_columns:2"),
    ]
    once = resolve_table_regions(decisions, BLOCKS)
    assert resolve_table_regions(once, BLOCKS) == once
