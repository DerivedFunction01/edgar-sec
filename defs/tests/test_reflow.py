"""Contract tests for the conservative ASCII reflow engine."""

from __future__ import annotations

from defs.tables.table_policy import split_structural_table_intro
from defs.text.reflow import (
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    ReflowPolicy,
    reflow_ascii,
)
from defs.text.reflow.engine import _merge_adjacent_prose_decisions
from defs.text.reflow.types import SpanDecision

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


def test_policy_unwraps_front_matter_prose_but_preserves_structure() -> None:
    text = (
        "FORM 10-K/A\n"
        "\n"
        "The purpose of this amendment is to clarify the following\n"
        "disclosures and update the related explanatory note.\n"
        "\n"
        "PART I\n"
        "\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "The company operates worldwide.\n"
    )
    result = reflow_ascii(
        text,
        body_start_line=9,
        policy=ReflowPolicy(
            unwrap_pre_body_prose=True,
            relax_prose_layout_gaps=True,
        ),
    )

    assert "clarify the following disclosures and update" in result.text
    assert "note.\n\nPART I" in result.text


def test_policy_unwraps_explanatory_note_with_form_references() -> None:
    from defs.sec_forms.cover.reflow import is_cover_layout_line

    text = (
        "FORM 10-K\n"
        "\n"
        "Explanatory Note\n"
        "\n"
        "This amendment does not reflect events occurring after the original filing of\n"
        "the Annual Report on Form 10-K, as previously amended, or modify or update those\n"
        "disclosures as presented in the Form 10-K, as previously amended.\n"
        "\n"
        "PART I\n"
    )
    result = reflow_ascii(
        text,
        body_start_line=8,
        policy=ReflowPolicy(
            unwrap_pre_body_prose=True,
            relax_prose_layout_gaps=True,
            is_structural_line=is_cover_layout_line,
        ),
    )
    assert (
        "original filing of the Annual Report on Form 10-K, as previously amended, or modify"
        in result.text
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


def test_justified_prose_with_inline_numbers_is_unwrapped() -> None:
    text = (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "Metals  Packaging,  which accounted for  approximately  82% of consolidated  net\n"
        "sales  and  approximately  81% of  consolidated  operating  income  in 1997,\n"
        "employed  approximately  32,000 persons  across  various manufacturing sites."
    )
    result = reflow_ascii(text, body_start_line=3)
    assert "<TABLE>" not in result.text
    assert "82% of consolidated  net sales" in result.text
    assert any(d.action == ACTION_UNWRAP for d in result.decisions)


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


def test_complete_signature_layout_is_protected_across_blank_lines() -> None:
    text = (
        "Signature                     Title                         Date\n\n"
        "/s/Gary L. Westerholm\n"
        "_____________________\n"
        "Gary L. Westerholm       President, Chief Executive\n"
        "                         Officer and Director           January 13, 2004\n\n"
        "/s/John DiMora\n"
        "______________\n"
        "John DiMora                    Director                 January 13, 2004\n\n"
        "John W. Sawarin                Director\n\n"
        "After section"
    )
    result = reflow_ascii(text, body_start_line=0)
    assert result.text == text
    assert len(result.protected_signatures) == 1
    assert result.protected_signatures[0].start_line == 0
    assert result.protected_signatures[0].end_line == 12
    assert "<TABLE>" not in result.text


def test_generic_table_intro_cue_splits_only_before_table_geometry() -> None:
    intro = "The following information is presented below"
    table = "Name                  2024       2023\nAlpha                 10         9"
    narrative, table_lines = split_structural_table_intro((intro, table))
    assert narrative == (intro,)
    assert table_lines == (table,)


def test_filing_specific_prose_is_not_a_table_intro_cue() -> None:
    lines = (
        "The fair value was estimated using assumptions",
        "Name                  2024       2023",
        "Alpha                 10         9",
    )
    narrative, table_lines = split_structural_table_intro(lines)
    assert narrative == ()
    assert table_lines == lines


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


def test_reflow_puts_inline_table_tags_on_own_lines() -> None:
    text = "prefix <TABLE>\nA 1\n</TABLE> suffix"

    result = reflow_ascii(text, body_start_line=0)

    assert result.text == "prefix\n<TABLE>\nA 1\n</TABLE>\nsuffix"


def test_table_continuity_bridges_header_body_blank_line() -> None:
    text = (
        "Revenue by segment       2024       2023\n"
        "-----------------------  ---------- ----------\n"
        "\n"
        "Automotive               $1,200     $1,100\n"
        "Industrial               $2,050     $1,980\n"
    )

    result = reflow_ascii(text, body_start_line=0)

    assert result.text.count("<TABLE>") == 1
    assert "-----------------------" in result.text
    assert "Industrial               $2,050     $1,980" in result.text


def test_multiline_financial_header_is_inside_inferred_table() -> None:
    text = (
        "CONSOLIDATED BALANCE SHEETS\n"
        "For the Years Ended December 31, 2004 and 2003\n"
        "\n"
        "(Amounts in thousands)\n"
        "\n"
        "2004                         2003\n"
        "-------------------------    -------------------------\n"
        "Cash                         100        90\n"
        "Other assets                 200       180\n"
        "Total assets                 300       270\n"
    )

    result = reflow_ascii(text, body_start_line=0)

    assert result.text.count("<TABLE>") == 1
    table = result.text.split("<TABLE>\n", 1)[1].split("\n</TABLE>", 1)[0]
    assert "CONSOLIDATED BALANCE SHEETS" in table
    assert "For the Years Ended December 31, 2004 and 2003" in table
    assert "(Amounts in thousands)" in table
    assert "2004                         2003" in table
    assert "-------------------------" in table


def test_balance_sheet_sections_and_tail_form_one_table() -> None:
    text = (
        "CONSOLIDATED BALANCE SHEETS\n"
        "2004                         2003\n"
        "Cash                         100        90\n"
        "Other assets                 200       180\n"
        "Total assets                 300       270\n"
        "\n"
        "LIABILITIES AND STOCKHOLDERS' EQUITY\n"
        "\n"
        "Current liabilities           50        45\n"
        "Long-term debt                50        45\n"
        "Total liabilities and stockholders' equity  100  90\n"
        "=======================================  ======\n"
    )

    result = reflow_ascii(text, body_start_line=0)

    assert result.text.count("<TABLE>") == 1
    assert result.text.count("</TABLE>") == 1
    table = result.text.split("<TABLE>\n", 1)[1].split("\n</TABLE>", 1)[0]
    assert "LIABILITIES AND STOCKHOLDERS' EQUITY" in table
    assert "Total liabilities and stockholders' equity" in table


def test_table_continuity_bridges_page_marker() -> None:
    text = (
        "Revenue by segment       2024       2023\n"
        "-----------------------  ---------- ----------\n"
        "Automotive               $1,200     $1,100\n"
        "<page>F-1\n"
        "Industrial               $2,050     $1,980\n"
        "Total                    $3,250     $3,080\n"
    )

    result = reflow_ascii(text, body_start_line=0)

    assert result.text.count("<TABLE>") == 1
    assert "<page>F-1" in result.text
    assert "Total                    $3,250     $3,080" in result.text


def test_table_continuity_bridges_wrapped_description_to_numeric_tail() -> None:
    text = (
        "Description                         2024       2023\n"
        "-----------------------------------  ---------  ---------\n"
        "Government assistance, non-interest\n"
        "bearing, repayable in quarterly\n"
        "payments commencing October 1, 2024       395,778    369,550\n"
        "-----------------------------------  ---------  ---------\n"
        "Following prose begins here.\n"
    )

    result = reflow_ascii(text, body_start_line=0)

    assert result.text.count("<TABLE>") == 1
    assert "payments commencing October 1, 2024       395,778    369,550" in result.text
    assert "Following prose begins here." in result.text.split("</TABLE>", 1)[1]


def test_table_continuity_bridges_structural_statement_section() -> None:
    text = (
        "Total liabilities             4,868,402    3,856,168\n"
        "                              ----------   ----------\n"
        "\n"
        "Commitments and Contingencies (note 15)\n"
        "\n"
        "Stockholders' equity (deficit):\n"
        "\n"
        "Common stock                       24,818       23,649\n"
        "Additional paid in capital     20,133,739   16,781,788\n"
        "Total stockholders' deficit    (3,252,981)  (2,983,592)\n"
        "                              ------------ ------------\n"
        "Total liabilities and stockholders' deficit\t     $\t1,615,421  $\t872,576\n"
        "                              ============ ============"
    )
    result = reflow_ascii(text, body_start_line=0)
    assert result.text.count("<TABLE>") == 1
    assert "Commitments and Contingencies (note 15)" in result.text
    assert "Total liabilities and stockholders' deficit" in result.text
    assert (
        result.text.endswith("</TABLE>")
        or "</TABLE>"
        in result.text.split("Total liabilities and stockholders' deficit")[1]
    )


def test_tab_indented_bullet_continuation_unwraps_without_table_policy() -> None:
    text = "o   First line of a prose bullet\n\tcontinuation of the same bullet\n"

    result = reflow_ascii(
        text,
        body_start_line=0,
        policy=ReflowPolicy(unwrap_bullet_continuations=True),
    )

    assert (
        result.text
        == "o   First line of a prose bullet continuation of the same bullet\n"
    )


def test_tab_indented_paragraph_unwraps_with_indent() -> None:
    text = (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "\tMcKenzie Bay International, Ltd. and subsidiaries (Company) is a\n"
        "\tdevelopment stage company with no operations.  The Company's primary\n"
        "\tbusiness activity is the development of wind powered alternative energy\n"
        "\tsystems.\n"
    )
    result = reflow_ascii(text, body_start_line=3)
    assert "<TABLE>" not in result.text
    assert (
        "\tMcKenzie Bay International, Ltd. and subsidiaries (Company) is a development stage "
        "company with no operations.  The Company's primary business activity is the development "
        "of wind powered alternative energy systems."
    ) in result.text


def test_bracketed_list_marker_unwraps() -> None:
    text = (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        " 1.\tNature of operations\n"
        "\n"
        " \t[a]\tBasis of presentation\n"
        "\n"
        " \t\tThe financial statements of the Company have been prepared on\n"
        "\t\tthe basis of the Company continuing as a going concern, which\n"
        "\t\tcontemplates the realization of assets and the payment of\n"
        "\t\tliabilities in the ordinary course of business.\n"
    )
    result = reflow_ascii(text, body_start_line=3)
    assert "<TABLE>" not in result.text
    assert " 1.\tNature of operations" in result.text
    assert " \t[a]\tBasis of presentation" in result.text
    assert (
        "The financial statements of the Company have been prepared on the basis of the Company continuing"
        in result.text
    )


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


def test_table_interrupted_prose_is_unified() -> None:
    text = (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "The following table summarizes revenue for the\n"
        "years ended December 31, 2024 and 2023:\n"
        "\n"
        "<TABLE>\n"
        "Revenue by segment       2024       2023\n"
        "  Automotive             $1,200     $1,100\n"
        "  Industrial             $2,050     $1,980\n"
        "</TABLE>\n"
        "\n"
        "and shows strong growth across all segments."
    )
    result = reflow_ascii(text, body_start_line=3)
    # The prose following the table should be unified with the sentence preceding it
    assert (
        "years ended December 31, 2024 and 2023: and shows strong growth across all segments."
        in result.text
    )


def test_policy_callbacks_recognize_domain_specific_table_sections() -> None:
    text = (
        "Assets                    2024       2023\n"
        "Cash                      100        90\n"
        "Other assets              200        180\n"
        "\n"
        "LIABILITIES AND STOCKHOLDERS' EQUITY\n"
        "\n"
        "Total liabilities         100        90\n"
        "                              ======== ========\n"
    )
    result = reflow_ascii(
        text,
        body_start_line=0,
        policy=ReflowPolicy(
            is_table_bridge_line=lambda line: "LIABILITIES" in line.upper(),
            is_table_tail_line=lambda line: line.lower().startswith(
                "total liabilities"
            ),
        ),
    )

    assert result.text.count("<TABLE>") == 1
    assert "LIABILITIES AND STOCKHOLDERS' EQUITY" in result.text
    assert "Total liabilities" in result.text


def test_default_tail_policy_does_not_match_generic_total_word() -> None:
    text = "Description                 2024       2023\nTotal commentary follows"
    result = reflow_ascii(text, body_start_line=0)

    assert "<TABLE>" not in result.text
