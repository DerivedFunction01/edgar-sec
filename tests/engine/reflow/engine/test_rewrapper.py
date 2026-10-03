"""The reflow stage: segmentation, decisions, boundary resolution, rendering.
Filing-sized documents live in `conftest.py`; each test states the one property
it holds one of them to.
"""

from __future__ import annotations

from edgar_sec.domain.taxonomy.statements.predicates import (
    is_financial_table_bridge_line,
    is_financial_table_tail_line,
)
from edgar_sec.engine.document.page_markers.signatures import (
    SignatureRegion,
    mask_signature_regions,
    restore_signature_regions,
)
from edgar_sec.engine.forms.cover.reflow import is_checkbox_answer_line
from edgar_sec.engine.reflow.engine.rewrapper import (
    _merge_adjacent_prose_decisions,
    reflow_ascii,
)
from edgar_sec.engine.reflow.types import (
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    ReflowPolicy,
    SpanDecision,
)
from tests.engine.reflow.engine.conftest import TAGGED_TABLE

BODY_START = 3

PROSE = (
    "PART I\n"
    "ITEM 1. BUSINESS\n"
    "\n"
    "We are an enterprise software company\n"
    "founded in 1998 that sells products\n"
    "across multiple market segments today."
)

PRODUCTION_POLICY = ReflowPolicy(
    unwrap_pre_body_prose=True,
    relax_prose_layout_gaps=True,
    unwrap_bullet_continuations=True,
    is_checkbox_answer_line=is_checkbox_answer_line,
    is_structural_line=lambda line: line.startswith("FORM "),
    is_table_bridge_line=is_financial_table_bridge_line,
    is_table_tail_line=is_financial_table_tail_line,
)


def _reflow(text: str, body_start: int = BODY_START) -> object:
    return reflow_ascii(text, body_start_line=body_start)


def test_empty_text_and_single_line_text_are_returned_unchanged() -> None:
    for text in ("", "one line"):
        result = reflow_ascii(text, body_start_line=0)
        assert result.text == text
        assert result.decisions == ()


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
    assert reflow_ascii(text, body_start_line=2).text == text


def test_a_pre_body_table_is_never_tagged() -> None:
    text = (
        "FORM 10-K\n\n"
        "Name                  2024       2023\n"
        "Alpha                 10         9\n\n"
        "PART I\n\n"
        "The company operates worldwide.\n"
    )
    result = reflow_ascii(
        text, body_start_line=5, policy=ReflowPolicy(unwrap_pre_body_prose=True)
    )
    assert result.text.count("<TABLE>") == 0


def test_hard_wrapped_prose_is_unwrapped() -> None:
    result = _reflow(PROSE)
    assert result.text == (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "We are an enterprise software company founded in 1998 that sells "
        "products across multiple market segments today."
    )
    unwrap = [d for d in result.decisions if d.action == ACTION_UNWRAP]
    assert len(unwrap) == 1
    assert unwrap[0].trace == "fast_prose"


def test_justified_prose_with_double_spaces_is_still_unwrapped() -> None:
    text = (
        "PART I\nITEM 1. BUSINESS\n\n"
        "We believe  the company  will continue  to grow\n"
        "because  demand remains  strong across  regions."
    )
    result = _reflow(text)
    assert "<TABLE>" not in result.text
    assert (
        "We believe  the company  will continue  to grow because  demand "
        "remains  strong across  regions."
    ) in result.text


def test_justified_prose_with_inline_numbers_is_unwrapped(
    justified_prose_with_numbers: str,
) -> None:
    result = _reflow(justified_prose_with_numbers)
    assert "<TABLE>" not in result.text
    assert "82% of consolidated  net sales" in result.text
    assert any(d.action == ACTION_UNWRAP for d in result.decisions)


def test_financial_narrative_with_one_aligned_numeric_column_is_not_tagged(
    financial_narrative: str,
) -> None:
    result = reflow_ascii(
        financial_narrative,
        body_start_line=0,
        policy=ReflowPolicy(relax_prose_layout_gaps=True),
    )
    assert "<TABLE>" not in result.text
    assert any(d.action == ACTION_UNWRAP for d in result.decisions)


def test_blank_separated_single_numeric_rows_form_one_complete_table() -> None:
    rows = (
        "Product A                  $100.00    Industrial units     Active",
        "Product B                  $200.00    Industrial units     Active",
        "Product C                  $300.00    Industrial units     Active",
    )
    text = (
        "The report discusses the operating results.\n\n"
        + "\n\n".join(rows)
        + "\n\nThe report then discusses future plans."
    )

    result = reflow_ascii(text, body_start_line=0)

    assert result.text.count("<TABLE>") == 1
    assert result.text.count("</TABLE>") == 1
    table = result.text.split("<TABLE>\n", 1)[1].split("\n</TABLE>", 1)[0]
    assert table == "\n\n".join(rows)
    assert result.text.startswith(
        "The report discusses the operating results.\n\n<TABLE>"
    )
    assert result.text.endswith("</TABLE>\n\nThe report then discusses future plans.")
    assert any(
        "repeated_row_geometry" in decision.evidence for decision in result.decisions
    )


def test_confirmed_row_runs_join_across_a_subtotal_and_year_label() -> None:
    rows = (
        "Product A                  $100.00    Industrial units     Active",
        "Product B                  $200.00    Industrial units     Active",
        "Product C                  $300.00    Industrial units     Active",
        "Product D                  $400.00    Industrial units     Active",
        "Product E                  $500.00    Industrial units     Active",
        "Product F                  $600.00    Industrial units     Active",
    )
    text = (
        "The schedule begins.\n\n"
        + "\n\n".join(rows[:3])
        + "\n\nSub-total 2000           $600.00\n"
        + "--------------           ---------\n\n2001\n\n"
        + "\n\n".join(rows[3:])
        + "\n\nThe schedule ends."
    )

    result = reflow_ascii(text, body_start_line=0)

    assert result.text.count("<TABLE>") == 1
    table = result.text.split("<TABLE>\n", 1)[1].split("\n</TABLE>", 1)[0]
    assert table == (
        "\n\n".join(rows[:3])
        + "\n\nSub-total 2000           $600.00\n"
        + "--------------           ---------\n\n2001\n\n"
        + "\n\n".join(rows[3:])
    )
    assert result.text.startswith("The schedule begins.\n\n<TABLE>")
    assert result.text.endswith("</TABLE>\n\nThe schedule ends.")


def test_bullet_prefix_survives_unwrap() -> None:
    text = (
        "PART I\nITEM 1. BUSINESS\n\n"
        "    (a) The company manufactures widgets and sells them\n"
        "        throughout the United States and Canada."
    )
    result = _reflow(text)
    assert (
        "    (a) The company manufactures widgets and sells them throughout"
        in result.text
    )
    assert "the United States and Canada." in result.text


def test_tab_indented_paragraph_unwraps_with_indent() -> None:
    text = (
        "PART I\nITEM 1. BUSINESS\n\n"
        "\tMcKenzie Bay International, Ltd. and subsidiaries (Company) is a\n"
        "\tdevelopment stage company with no operations.  The Company's primary\n"
        "\tbusiness activity is the development of wind powered alternative energy\n"
        "\tsystems.\n"
    )
    result = _reflow(text)
    assert "<TABLE>" not in result.text
    assert (
        "\tMcKenzie Bay International, Ltd. and subsidiaries (Company) is a development stage "
        "company with no operations.  The Company's primary business activity is the development "
        "of wind powered alternative energy systems."
    ) in result.text


def test_bracketed_list_marker_unwraps() -> None:
    text = (
        "PART I\nITEM 1. BUSINESS\n\n"
        " 1.\tNature of operations\n\n"
        " \t[a]\tBasis of presentation\n\n"
        " \t\tThe financial statements of the Company have been prepared on\n"
        "\t\tthe basis of the Company continuing as a going concern, which\n"
        "\t\tcontemplates the realization of assets and the payment of\n"
        "\t\tliabilities in the ordinary course of business.\n"
    )
    result = _reflow(text)
    assert "<TABLE>" not in result.text
    assert " 1.\tNature of operations" in result.text
    assert " \t[a]\tBasis of presentation" in result.text
    assert (
        "The financial statements of the Company have been prepared on the basis"
        in result.text
    )


def test_tab_indented_bullet_continuation_unwraps_with_the_policy_flag() -> None:
    text = "o   First line of a prose bullet\n\tcontinuation of the same bullet\n"
    expected = "o   First line of a prose bullet continuation of the same bullet\n"
    assert reflow_ascii(text, body_start_line=0).text != expected
    with_flag = reflow_ascii(
        text, body_start_line=0, policy=ReflowPolicy(unwrap_bullet_continuations=True)
    )
    assert with_flag.text == expected


def test_justified_prose_with_layout_gaps_is_preserved() -> None:
    text = (
        "PART I\nITEM 1. BUSINESS\n\n"
        "We believe   the company will continue to grow\n"
        "because   demand remains strong across regions."
    )
    result = _reflow(text)
    assert result.text == text
    assert all(d.action == ACTION_PRESERVE for d in result.decisions)


def test_tab_separated_layout_is_preserved() -> None:
    text = "PART I\nITEM 1. BUSINESS\n\nName:\tValue:\tOther:\nAlpha\t1\t2"
    assert _reflow(text).text == text


def test_dot_leader_toc_rows_form_a_table() -> None:
    text = (
        "PART I\nITEM 1. BUSINESS\n\n"
        "Item 1. Business ................. 1\n"
        "Item 1A. Risk Factors ............ 5\n"
        "Item 2. Properties ............... 8"
    )
    result = _reflow(text)
    assert result.text.count("<TABLE>") == result.text.count("</TABLE>") == 1
    assert "<TABLE>\nItem 1. Business ................. 1" in result.text


def test_structural_sgml_markers_are_preserved() -> None:
    text = "PART I\nITEM 1. BUSINESS\n\n<S>  <C>\nAssets 10 20\n<C> more"
    assert _reflow(text).text == text


def test_signature_block_is_preserved_not_tagged() -> None:
    text = (
        "PART I\nITEM 1. BUSINESS\n\n"
        "Date: March 1, 2024\nBy: /s/ Jane Doe\nTitle: Chief Executive Officer"
    )
    result = _reflow(text)
    assert result.text == text
    assert all(d.action == ACTION_PRESERVE for d in result.decisions)


def test_signature_regions_are_reported_and_restored(signature_block: str) -> None:
    result = reflow_ascii(signature_block, body_start_line=0)
    assert result.text == signature_block
    assert len(result.protected_signatures) == 1
    assert isinstance(result.protected_signatures[0], SignatureRegion)
    assert result.protected_signatures[0].start_line == 0
    assert result.protected_signatures[0].end_line == 12
    assert "<TABLE>" not in result.text


def test_signature_masking_is_restored_byte_for_byte(signature_block: str) -> None:
    masked, regions = mask_signature_regions(signature_block)
    assert masked != signature_block
    assert len(regions) == 1
    assert restore_signature_regions(masked, regions) == signature_block


def test_repeated_numeric_columns_are_tagged_and_preserved(
    repeated_numeric_columns: str,
) -> None:
    result = _reflow(repeated_numeric_columns)
    assert "<TABLE>" in result.text
    assert "</TABLE>" in result.text
    assert "Revenue by segment       2024       2023" in result.text
    assert "  Total                  $3,250     $3,080" in result.text
    tag = [d for d in result.decisions if d.action == ACTION_TAG_AND_PRESERVE]
    assert len(tag) == 1
    assert tag[0].evidence[0] == "repeated_numeric_columns:2"


def test_dense_single_numeric_column_schedule_still_tags() -> None:
    text = (
        "Revenue by domestic service\n"
        "Domestic ASDS 9.6/56/64 kbps                                 25%\n"
        "Domestic DDS                                                 40%\n"
        "Domestic ACCUNET T1.5                                        55%\n"
        "Domestic ACCUNET T45                                         50%"
    )
    result = reflow_ascii(text, body_start_line=0)
    assert result.text.count("<TABLE>") == 1
    assert result.text.count("</TABLE>") == 1


def test_existing_tagged_table_survives_exactly() -> None:
    text = f"PART I\nITEM 1. BUSINESS\n\n{TAGGED_TABLE}\n\nafter prose"
    result = _reflow(text)
    assert TAGGED_TABLE in result.text
    assert result.protected_tables


def test_existing_tagged_table_adjacent_to_prose_is_not_joined() -> None:
    tagged = "<TABLE>\n<S>  <C>\nA 10\n</TABLE>"
    text = f"PART I\nITEM 1. BUSINESS\n\nprose line\n{tagged}\nnext prose"
    result = _reflow(text)
    assert tagged in result.text
    assert "prose line\n<TABLE>" in result.text


def test_reflow_puts_inline_table_tags_on_own_lines() -> None:
    result = reflow_ascii("prefix <TABLE>\nA 1\n</TABLE> suffix", body_start_line=0)
    assert result.text == "prefix\n<TABLE>\nA 1\n</TABLE>\nsuffix"


def test_table_continuity_bridges_header_body_blank_line() -> None:
    text = (
        "Revenue by segment       2024       2023\n"
        "-----------------------  ---------- ----------\n\n"
        "Automotive               $1,200     $1,100\n"
        "Industrial               $2,050     $1,980\n"
    )
    result = reflow_ascii(text, body_start_line=0)
    assert result.text.count("<TABLE>") == 1
    assert "-----------------------" in result.text
    assert "Industrial               $2,050     $1,980" in result.text


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


def test_table_continuity_bridges_wrapped_description_to_numeric_tail(
    wrapped_description_table: str,
) -> None:
    result = reflow_ascii(wrapped_description_table, body_start_line=0)
    assert result.text.count("<TABLE>") == 1
    assert "payments commencing October 1, 2024       395,778    369,550" in result.text
    assert "Following prose begins here." in result.text.split("</TABLE>", 1)[1]


def test_table_continuity_bridges_structural_statement_section(
    structural_section_table: str,
) -> None:
    result = reflow_ascii(structural_section_table, body_start_line=0)
    assert result.text.count("<TABLE>") == 1
    assert "Commitments and Contingencies (note 15)" in result.text
    assert "Total liabilities and stockholders' deficit" in result.text


def test_blank_line_between_aligned_rows_is_bridged() -> None:
    text = (
        "PART I\nITEM 1. BUSINESS\n\n"
        "Revenue by segment       2024       2023\n"
        "  Automotive             $1,200     $1,100\n"
        "  Industrial             $2,050     $1,980\n\n"
        "Operating expenses       2024       2023\n"
        "  Selling                $800       $750\n"
        "  General                $900       $870\n\n"
        "after prose"
    )
    result = _reflow(text)
    assert result.text.count("<TABLE>") == 1
    assert result.text.count("</TABLE>") == 1
    assert "<TABLE>\nRevenue by segment       2024       2023" in result.text
    assert "  General                $900       $870\n</TABLE>" in result.text
    tag = [d for d in result.decisions if d.action == ACTION_TAG_AND_PRESERVE]
    assert len(tag) == 1
    assert "bridged_blank_line" in tag[0].evidence


def test_two_blank_lines_are_not_bridged() -> None:
    text = (
        "PART I\nITEM 1. BUSINESS\n\n"
        "Revenue by segment       2024       2023\n"
        "  Automotive             $1,200     $1,100\n"
        "  Industrial             $2,050     $1,980\n\n\n"
        "Other amounts           2024       2023\n"
        "  Selling                $700       $690\n"
        "  General                $900       $870\n\n"
        "after prose"
    )
    assert _reflow(text).text.count("<TABLE>") == 2


def test_multiline_financial_header_is_inside_inferred_table() -> None:
    text = (
        "CONSOLIDATED BALANCE SHEETS\n"
        "For the Years Ended December 31, 2004 and 2003\n\n"
        "(Amounts in thousands)\n\n"
        "2004                         2003\n"
        "-------------------------    -------------------------\n"
        "Cash                         100        90\n"
        "Other assets                 200       180\n"
        "Total assets                 300       270\n"
    )
    result = reflow_ascii(text, body_start_line=0)
    assert result.text.count("<TABLE>") == 1
    table = result.text.split("<TABLE>\n", 1)[1].split("\n</TABLE>", 1)[0]
    for expected in (
        "CONSOLIDATED BALANCE SHEETS",
        "For the Years Ended December 31, 2004 and 2003",
        "(Amounts in thousands)",
        "2004                         2003",
        "-------------------------",
    ):
        assert expected in table


def test_balance_sheet_sections_and_tail_form_one_table(balance_sheet: str) -> None:
    result = reflow_ascii(balance_sheet, body_start_line=0)
    assert result.text.count("<TABLE>") == 1
    assert result.text.count("</TABLE>") == 1
    table = result.text.split("<TABLE>\n", 1)[1].split("\n</TABLE>", 1)[0]
    assert "LIABILITIES AND STOCKHOLDERS' EQUITY" in table
    assert "Total liabilities and stockholders' equity" in table


def test_multiline_table_extension_stops_before_financial_prose(
    long_term_debt_schedule: str,
) -> None:
    result = reflow_ascii(long_term_debt_schedule, body_start_line=0)
    assert result.text.count("<TABLE>") == 1
    assert result.text.count("</TABLE>") == 1
    table, following_prose = result.text.split("</TABLE>", 1)
    assert "Long-term debt                                         $ 434,392" in table
    assert "On June 5, 1998" not in table
    assert (
        "On June 5, 1998, in connection with the acquisition of Galileo Canada, the Company incurred"
        in following_prose
    )


def test_prose_introduction_between_tax_tables_stays_outside(
    tax_tables_with_prose_between: str,
) -> None:
    result = reflow_ascii(tax_tables_with_prose_between, body_start_line=0)
    assert result.text.count("<TABLE>") == 2
    assert result.text.count("</TABLE>") == 2
    before_intro, after_intro = result.text.split(
        "The tax effects of temporary differences that give rise to significant portions of the deferred tax assets are presented below:"
    )
    assert before_intro.rstrip().endswith("</TABLE>")
    assert after_intro.lstrip().startswith("<TABLE>")


def test_table_extension_does_not_absorb_filing_footer(tariff_page: str) -> None:
    result = reflow_ascii(tariff_page, body_start_line=0)
    assert result.text.count("<TABLE>") == 1
    assert "Domestic ACCUNET                 60%        55%\n</TABLE>" in result.text
    assert "</TABLE>\n\nAT&T COMMUNICATIONS" in result.text


def test_numbered_section_heading_stays_outside_table(property_schedule: str) -> None:
    tagged = reflow_ascii(
        property_schedule,
        body_start_line=0,
        policy=ReflowPolicy(tag_untagged_tables=True),
    )
    assert tagged.text.count("<TABLE>") == 1
    body = tagged.text.split("<TABLE>")[1].split("</TABLE>")[0]
    assert "2.      PROPERTY AND EQUIPMENT:" not in body
    assert (
        "$643,402\n                                                               ========="
        in body
    )
    untagged = reflow_ascii(
        property_schedule,
        body_start_line=0,
        policy=ReflowPolicy(tag_untagged_tables=False),
    )
    assert untagged.text.count("<TABLE>") == 0
    assert "$643,402" in untagged.text


def test_header_expansion_stops_at_protected_table_before_inferred_table(
    lease_intro_then_debt_table: str,
) -> None:
    result = reflow_ascii(lease_intro_then_debt_table, body_start_line=0)
    assert (
        "operating leases at December 31, 1999 are as follows:\n<TABLE>" in result.text
    )
    assert result.text.count("<TABLE>") == 2
    assert result.text.count("</TABLE>") == 2
    assert any(
        "expanded_table_header" in decision.evidence
        and decision.action == ACTION_TAG_AND_PRESERVE
        for decision in result.decisions
    )


def test_interleaved_fiscal_period_subheadings_unify(
    fiscal_period_schedule: str,
) -> None:
    result = reflow_ascii(
        fiscal_period_schedule,
        body_start_line=0,
        policy=ReflowPolicy(tag_untagged_tables=True),
    )
    assert result.text.count("<TABLE>") == 1
    for expected in (
        "High          Low",
        "Fiscal 1998",
        "Fiscal 1999",
        "First  Quarter              1.312          .771",
    ):
        assert expected in result.text


def test_unit_header_with_period_columns_absorbed(unit_header_schedule: str) -> None:
    result = reflow_ascii(
        unit_header_schedule,
        body_start_line=0,
        policy=ReflowPolicy(tag_untagged_tables=True),
    )
    assert result.text.count("<TABLE>") == 1
    for expected in (
        "(in thousands, except per share data)",
        "2003       2002",
        "Total current assets",
    ):
        assert expected in result.text


def test_table_interrupted_prose_is_unified() -> None:
    text = (
        "PART I\nITEM 1. BUSINESS\n\n"
        "The following table summarizes revenue for the\n"
        "years ended December 31, 2024 and 2023:\n\n"
        "<TABLE>\n"
        "Revenue by segment       2024       2023\n"
        "  Automotive             $1,200     $1,100\n"
        "  Industrial             $2,050     $1,980\n"
        "</TABLE>\n\n"
        "and shows strong growth across all segments."
    )
    result = _reflow(text)
    assert (
        "years ended December 31, 2024 and 2023: and shows strong growth across all segments."
        in result.text
    )


def test_generic_table_intro_cue_splits_only_before_table_geometry() -> None:
    text = (
        "The following information is presented below\n"
        "Name                  2024       2023\n"
        "------------------------------------------ ----------\n"
        "Alpha                 10         9\n"
        "Beta                  11         8"
    )
    result = reflow_ascii(text, body_start_line=0)
    assert result.text == (
        "The following information is presented below\n"
        "<TABLE>\n"
        "Name                  2024       2023\n"
        "------------------------------------------ ----------\n"
        "Alpha                 10         9\n"
        "Beta                  11         8\n"
        "</TABLE>"
    )


def test_filing_specific_prose_is_not_a_table_intro_cue() -> None:
    text = (
        "The fair value was estimated using assumptions\n"
        "Name                  2024       2023\n"
        "------------------------------------------ ----------\n"
        "Alpha                 10         9\n"
        "Beta                  11         8"
    )
    result = reflow_ascii(text, body_start_line=0)
    body = result.text.split("<TABLE>\n", 1)[1].split("\n</TABLE>", 1)[0]
    assert "The fair value was estimated using assumptions" in body


def test_policy_unwraps_front_matter_prose_but_preserves_structure() -> None:
    text = (
        "FORM 10-K/A\n\n"
        "The purpose of this amendment is to clarify the following\n"
        "disclosures and update the related explanatory note.\n\n"
        "PART I\n\nITEM 1. BUSINESS\n\nThe company operates worldwide.\n"
    )
    result = reflow_ascii(
        text,
        body_start_line=9,
        policy=ReflowPolicy(unwrap_pre_body_prose=True, relax_prose_layout_gaps=True),
    )
    assert "clarify the following disclosures and update" in result.text
    assert "note.\n\nPART I" in result.text


def test_policy_unwraps_explanatory_note_with_form_references(
    explanatory_note: str,
) -> None:
    result = reflow_ascii(
        explanatory_note,
        body_start_line=8,
        policy=ReflowPolicy(
            unwrap_pre_body_prose=True,
            relax_prose_layout_gaps=True,
            is_structural_line=lambda line: line.startswith("FORM "),
        ),
    )
    assert (
        "original filing of the Annual Report on Form 10-K, as previously amended, or modify"
        in result.text
    )


def test_policy_callbacks_recognize_domain_specific_table_sections() -> None:
    text = (
        "Assets                    2024       2023\n"
        "Cash                      100        90\n"
        "Other assets              200        180\n\n"
        "LIABILITIES AND STOCKHOLDERS' EQUITY\n\n"
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
    result = reflow_ascii(
        "Description                 2024       2023\nTotal commentary follows",
        body_start_line=0,
    )
    assert "<TABLE>" not in result.text


def test_merge_joins_contiguous_prose_blocks_and_keeps_the_lower_confidence() -> None:
    merged = _merge_adjacent_prose_decisions(
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
    assert merged == [
        SpanDecision(
            ACTION_UNWRAP,
            10,
            18,
            0.65,
            ("ordinary_prose", "relaxed_prose_layout"),
            "fast_prose",
        )
    ]


def test_merge_leaves_a_protected_block_between_two_prose_blocks() -> None:
    decisions = [
        SpanDecision(ACTION_UNWRAP, 0, 2, 0.7, (), "fast_prose"),
        SpanDecision(ACTION_PRESERVE, 2, 4, 1.0, (), "hard_preserve"),
        SpanDecision(ACTION_UNWRAP, 4, 6, 0.7, (), "fast_prose"),
    ]
    assert _merge_adjacent_prose_decisions(decisions) == decisions


def test_merge_joins_prose_across_one_blank_line_and_not_two() -> None:
    one_gap = [
        SpanDecision(ACTION_UNWRAP, 0, 2, 0.7, (), "fast_prose"),
        SpanDecision(ACTION_UNWRAP, 3, 5, 0.7, (), "fast_prose"),
    ]
    assert _merge_adjacent_prose_decisions(one_gap) == [
        SpanDecision(ACTION_UNWRAP, 0, 5, 0.7, (), "fast_prose")
    ]
    two_gaps = [
        SpanDecision(ACTION_UNWRAP, 0, 2, 0.7, (), "fast_prose"),
        SpanDecision(ACTION_UNWRAP, 4, 6, 0.7, (), "fast_prose"),
    ]
    assert _merge_adjacent_prose_decisions(two_gaps) == two_gaps


def test_merge_never_joins_a_bullet_continuation() -> None:
    decisions = [
        SpanDecision(
            ACTION_UNWRAP, 0, 2, 0.8, ("bullet_prose_continuation",), "bullet_reflow"
        ),
        SpanDecision(ACTION_UNWRAP, 2, 4, 0.7, ("ordinary_prose",), "fast_prose"),
    ]
    assert _merge_adjacent_prose_decisions(decisions) == decisions


def test_decisions_are_deterministic() -> None:
    text = "PART I\nITEM 1. BUSINESS\n\nRevenue       2024\n  A           $1,000\n  B             $500"
    first, second = (reflow_ascii(text, body_start_line=3) for _ in range(2))
    assert (first.text, first.decisions) == (second.text, second.decisions)
