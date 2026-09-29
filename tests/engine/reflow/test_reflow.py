"""Contract tests for the conservative ASCII reflow engine."""

from __future__ import annotations

from edgar_sec.engine.reflow.engine import (
    _merge_adjacent_prose_decisions,
    reflow_ascii,
)
from edgar_sec.engine.reflow.types import (
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    SpanDecision,
)

BODY_START = 3

PROSE = (
    "PART I\n"
    "ITEM 1. BUSINESS\n"
    "\n"
    "We are an enterprise software company\n"
    "founded in 1998 that sells products\n"
    "across multiple market segments today."
)

TABLE = (
    "Revenue by segment       2024       2023\n"
    "  Automotive             $1,200     $1,100\n"
    "  Industrial              $2,300     $2,050\n"
    "  Total                  $3,400     $3,150"
)


def _reflow(text: str, body_start: int = BODY_START):
    return reflow_ascii(text, body_start_line=body_start)


def test_hard_wrapped_prose_is_unwrapped() -> None:
    result = _reflow(PROSE)
    expected = (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "We are an enterprise software company founded in 1998 that sells "
        "products across multiple market segments today."
    )
    assert result.text == expected
    unwrap = [d for d in result.decisions if d.action == ACTION_UNWRAP]
    assert len(unwrap) == 1
    assert unwrap[0].trace == "fast_prose"


def test_adjacent_prose_decisions_are_joined() -> None:
    decisions = _merge_adjacent_prose_decisions(
        [
            SpanDecision(ACTION_UNWRAP, 10, 14, 0.7, ("ordinary_prose",), "fast_prose"),
            SpanDecision(
                ACTION_UNWRAP,
                14,
                18,
                0.65,
                ("relaxed_prose_layout",),
                "front_matter_prose",
            ),
        ]
    )
    assert decisions == [
        SpanDecision(
            ACTION_UNWRAP,
            10,
            18,
            0.65,
            ("ordinary_prose", "relaxed_prose_layout"),
            "fast_prose",
        )
    ]


def test_no_body_anchor_returns_text_unchanged() -> None:
    result = reflow_ascii(PROSE, body_start_line=None)
    assert result.text == PROSE
    assert result.decisions == ()


def test_pre_body_region_is_never_reflowed() -> None:
    result = _reflow(PROSE, body_start=len(PROSE.splitlines()))
    assert result.text == PROSE
    assert all(
        d.trace == "fast_noop" and d.evidence == ("pre_body_region",)
        for d in result.decisions
    )


def test_single_line_block_is_noop() -> None:
    text = "PART I\nITEM 1. BUSINESS\n\nOne line of body prose only.\n\nITEM 2"
    result = reflow_ascii(text, body_start_line=2)
    assert result.text == text


def test_repeated_numeric_columns_are_tagged_and_preserved() -> None:
    text = (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "The following table summarizes our results:\n"
        "\n"
        "Revenue by segment       2024       2023\n"
        "  Automotive             $1,200     $1,100\n"
        "  Industrial              $2,050     $1,980\n"
        "  Total                  $3,250     $3,080\n"
        "\n"
        "ITEM 2. PROPERTIES\n"
        "Our properties are described below."
    )
    result = reflow_ascii(text, body_start_line=3)
    assert "<TABLE>" in result.text
    assert "</TABLE>" in result.text
    assert "Revenue by segment       2024       2023" in result.text
    assert "  Total                  $3,250     $3,080" in result.text
    tag = [d for d in result.decisions if d.action == ACTION_TAG_AND_PRESERVE]
    assert len(tag) == 1
    assert tag[0].evidence[0] == "repeated_numeric_columns:2"


def test_financial_narrative_with_one_aligned_numeric_column_is_not_tagged() -> None:
    text = (
        "      Revenues  for  the  year  ended  December  31,  1998  increased  52.9%  to\n"
        "approximately  $20,224,000  from  approximately  $13,231,000  for the year ended\n"
        "December  31,  1997.   Approximately   5.4%  or  $380,000  of  the  increase  is\n"
        "attributable  to  increased  hours of service  provided  under  existing and new\n"
        "contracts in the State of New York.  The  remaining  increase of $6,613,000 is a\n"
        "result of the  acquisition  of seven  offices  in New Jersey in  December  1997,\n"
        "February 1998 and March 1998."
    )

    result = reflow_ascii(
        text,
        body_start_line=0,
    )
    assert "<TABLE>" not in result.text
