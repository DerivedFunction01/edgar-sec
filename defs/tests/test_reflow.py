"""Contract tests for the conservative ASCII reflow engine."""

from __future__ import annotations

from defs.text.reflow import (
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    reflow_ascii,
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
    # Table rows are preserved exactly between the tags.
    assert "Revenue by segment       2024       2023" in result.text
    assert "  Total                  $3,250     $3,080" in result.text
    tag = [d for d in result.decisions if d.action == ACTION_TAG_AND_PRESERVE]
    assert len(tag) == 1
    assert tag[0].evidence[0] == "repeated_numeric_columns:2"


def test_justified_prose_with_double_spaces_is_still_unwrapped() -> None:
    # Double-space typography alone is not a layout signal: justified prose
    # remains ordinary prose and joins with single spaces.
    text = (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "We believe  the company  will continue  to grow\n"
        "because  demand remains  strong across  regions."
    )
    result = reflow_ascii(text, body_start_line=3)
    assert "<TABLE>" not in result.text
    # Line joins use single spaces; intra-line typography is untouched.
    assert (
        "We believe  the company  will continue  to grow because  demand "
        "remains  strong across  regions."
    ) in result.text


def test_justified_prose_with_layout_gaps_is_preserved() -> None:
    # Three-plus space runs on every line are layout-shaped; without shared
    # alignment columns the block stays preserved, never unwrapped or tagged.
    text = (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "We believe   the company will continue to grow\n"
        "because   demand remains strong across regions."
    )
    result = reflow_ascii(text, body_start_line=3)
    assert result.text == text
    assert all(d.action == ACTION_PRESERVE for d in result.decisions)


def test_tab_separated_layout_is_preserved() -> None:
    text = "PART I\nITEM 1. BUSINESS\n\nName:\tValue:\tOther:\nAlpha\t1\t2"
    result = reflow_ascii(text, body_start_line=3)
    assert result.text == text


def test_dot_leader_toc_rows_are_preserved() -> None:
    text = (
        "PART I\nITEM 1. BUSINESS\n\n"
        "Item 1. Business ................. 1\n"
        "Item 1A. Risk Factors ............ 5\n"
        "\nmore prose here"
    )
    result = reflow_ascii(text, body_start_line=3)
    assert "Item 1. Business ................. 1" in result.text
    assert "<TABLE>" not in result.text


def test_signature_block_is_preserved_not_tagged() -> None:
    text = (
        "PART I\nITEM 1. BUSINESS\n\n"
        "Date: March 1, 2024\nBy: /s/ Jane Doe\nTitle: Chief Executive Officer"
    )
    result = reflow_ascii(text, body_start_line=3)
    assert result.text == text
    assert all(d.action == ACTION_PRESERVE for d in result.decisions)


def test_existing_tagged_table_survives_exactly() -> None:
    tagged = "<TABLE>\n<S>     <C>   <C>\nAssets   1,000   900\n</TABLE>"
    text = f"PART I\nITEM 1. BUSINESS\n\n{tagged}\n\nafter prose"
    result = reflow_ascii(text, body_start_line=3)
    assert tagged in result.text
    assert result.protected_tables


def test_existing_tagged_table_adjacent_to_prose_is_not_joined() -> None:
    tagged = "<TABLE>\n<S>  <C>\nA 10\n</TABLE>"
    text = f"PART I\nITEM 1. BUSINESS\n\nprose line\n{tagged}\nnext prose"
    result = reflow_ascii(text, body_start_line=3)
    assert tagged in result.text
    assert "prose line\n<TABLE>" in result.text


def test_decisions_are_deterministic() -> None:
    text = (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "Revenue       2024\n"
        "  A           $1,000\n"
        "  B             $500"
    )
    first = reflow_ascii(text, body_start_line=3)
    second = reflow_ascii(text, body_start_line=3)
    assert first.text == second.text
    assert first.decisions == second.decisions


def test_structural_sgml_markers_are_preserved() -> None:
    text = "PART I\nITEM 1. BUSINESS\n\n<S>  <C>\nAssets 10 20\n<C> more"
    result = reflow_ascii(text, body_start_line=3)
    assert result.text == text


def test_blank_line_between_aligned_rows_is_bridged() -> None:
    # One blank line between aligned data runs is one connected table when
    # both sides independently qualify for a tag.
    text = (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "Revenue by segment       2024       2023\n"
        "  Automotive             $1,200     $1,100\n"
        "  Industrial             $2,050     $1,980\n"
        "\n"
        "Operating expenses       2024       2023\n"
        "  Selling                $800       $750\n"
        "  General                $900       $870\n"
        "\n"
        "after prose"
    )
    result = reflow_ascii(text, body_start_line=3)
    # Exactly one table: one opening and one closing tag.
    assert result.text.count("<TABLE>") == 1
    assert result.text.count("</TABLE>") == 1
    # The bridging blank line is inside the table region: the tag opens
    # before the first table and closes after the last row of the second.
    assert "<TABLE>\nRevenue by segment       2024       2023" in result.text
    assert "  General                $900       $870\n</TABLE>" in result.text
    tag = [d for d in result.decisions if d.action == ACTION_TAG_AND_PRESERVE]
    assert len(tag) == 1
    assert "bridged_blank_line" in tag[0].evidence


def test_two_blank_lines_are_not_bridged() -> None:
    text = (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "Revenue by segment       2024       2023\n"
        "  Automotive             $1,200     $1,100\n"
        "  Industrial              $2,050     $1,980\n"
        "\n\n"
        "Other amounts           2024       2023\n"
        "  Selling                $700       $690\n"
        "  General                $900       $870\n"
        "\n"
        "after prose"
    )
    result = reflow_ascii(text, body_start_line=3)
    assert result.text.count("<TABLE>") == 2


def test_bullet_prefix_survives_unwrap() -> None:
    text = (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "    (a) The company manufactures widgets and sells them\n"
        "        throughout the United States and Canada."
    )
    result = reflow_ascii(text, body_start_line=3)
    assert (
        "    (a) The company manufactures widgets and sells them throughout "
        "the United States and Canada."
    ) in result.text
