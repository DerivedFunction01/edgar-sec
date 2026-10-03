"""Structural table-boundary predicates: header prefix, bridge, tail.

These three questions are all answered from a block's own lines, because a reflow
has to decide about a span without asking which statement it belongs to; the
bridge and tail predicates therefore accept a caller-supplied predicate for
labels that cannot be recognised on shape alone.
"""

from __future__ import annotations

from edgar_sec.engine.tables.structural import (
    is_header_prefix,
    is_structural_table_bridge,
    is_structural_table_tail,
)


def _bridge_line(line: str) -> bool:
    return line == "Total assets and other items presented in this statement"


def _tail_line(line: str) -> bool:
    return line.lower().startswith("total liabilities")


# --- header prefix ---------------------------------------------------------


def test_an_uppercase_statement_title_is_a_header_prefix() -> None:
    assert is_header_prefix(("CONSOLIDATED BALANCE SHEETS",))
    assert is_header_prefix(("CONSOLIDATED BALANCE SHEETS", "December 31, 2004"))


def test_a_dash_rule_is_a_header_prefix() -> None:
    assert is_header_prefix(("------   ------   ------",))
    assert is_header_prefix(("==========  ==========",))


def test_a_units_label_is_a_header_prefix() -> None:
    assert is_header_prefix(("(in thousands, except per share data)",))


def test_a_year_column_row_is_a_header_prefix() -> None:
    assert is_header_prefix(("2004                         2003",))


def test_a_period_subheading_is_a_header_prefix() -> None:
    assert is_header_prefix(("Fiscal 1998",))


def test_wide_column_gaps_alone_make_a_header_prefix() -> None:
    assert is_header_prefix(("Item 1. Business         1",))


def test_an_empty_or_blank_prefix_is_not_a_header_prefix() -> None:
    assert not is_header_prefix(())
    assert not is_header_prefix(("", "   "))


def test_a_sentence_is_not_a_header_prefix() -> None:
    assert not is_header_prefix(
        ("Property and equipment consist of the following at December 31, 1998:",)
    )


def test_a_long_label_colon_is_not_a_header_prefix() -> None:
    assert not is_header_prefix(("Property and equipment consist of:",))


def test_a_too_long_line_is_not_a_header_prefix() -> None:
    assert not is_header_prefix(("a b c d e f g h i j k l m n o p q r s t u",))


def test_a_tag_or_section_marker_is_not_a_header_prefix() -> None:
    assert not is_header_prefix(("<TABLE>",))
    assert not is_header_prefix(("PART II",))
    assert not is_header_prefix(("ITEM 8. FINANCIAL STATEMENTS",))
    assert not is_header_prefix(("Note 12. Basis of presentation",))
    assert not is_header_prefix(("EXHIBIT 4",))


def test_a_list_marker_is_not_a_header_prefix() -> None:
    assert not is_header_prefix(("1.  Nature of operations",))
    assert not is_header_prefix(("a.  Basis of presentation",))


def test_a_tab_indented_block_is_header_evidence_on_its_own() -> None:
    # A tab is formatting evidence even when the text is not a statement title,
    # which is why a list-shaped line is only rejected without indentation.
    assert is_header_prefix(("\tIndented header",))


def test_more_than_six_non_blank_lines_is_not_a_header_prefix() -> None:
    assert not is_header_prefix(tuple(f"Line {index}" for index in range(7)))


def test_table_intro_cue_is_not_a_header_prefix() -> None:
    assert not is_header_prefix(("The following table shows the estimated fair value",))
    assert not is_header_prefix(
        (
            "Aggregate annual maturities of notes payable and long-term debt",
            "are as follows:",
        )
    )
    assert not is_header_prefix(
        ("See Item 8. Financial Statements", "and Supplementary Data.")
    )
    assert not is_header_prefix(("Item 2.   Properties",))


# --- structural bridge -----------------------------------------------------


def test_an_uppercase_label_is_a_bridge() -> None:
    assert is_structural_table_bridge(("LIABILITIES AND STOCKHOLDERS' EQUITY",))


def test_an_exhibit_section_is_not_a_table_bridge() -> None:
    assert not is_structural_table_bridge(("EXHIBIT 4",))
    assert not is_structural_table_bridge(("EXHIBIT INDEX",))


def test_a_table_intro_is_not_a_bridge_even_if_the_caller_matches_it() -> None:
    intro = "The following table provides a summary of the assets:"
    assert not is_structural_table_bridge((intro,), is_bridge_line=lambda _: True)


def test_a_title_case_label_is_a_bridge() -> None:
    assert is_structural_table_bridge(("Commitments and Contingencies (note 15)",))


def test_a_period_subheading_is_a_bridge() -> None:
    assert is_structural_table_bridge(("Fiscal 1998",))


def test_a_separator_rule_inside_a_bridge_is_ignored() -> None:
    assert is_structural_table_bridge(("=======  ======", "CURRENT ASSETS"))


def test_a_sentence_is_not_a_bridge() -> None:
    assert not is_structural_table_bridge(
        ("The fair value was estimated using assumptions to prepare this schedule",)
    )
    assert not is_structural_table_bridge(
        ("We believe the company will continue to grow in the coming year",)
    )


def test_a_long_heading_needs_the_explicit_predicate() -> None:
    long_heading = "Total assets and other items presented in this statement"
    assert not is_structural_table_bridge((long_heading,))
    assert is_structural_table_bridge((long_heading,), is_bridge_line=_bridge_line)


def test_a_block_of_two_aligned_cells_is_not_a_bridge() -> None:
    assert not is_structural_table_bridge(("Product A                100        90",))


def test_an_empty_bridge_is_not_a_bridge() -> None:
    assert not is_structural_table_bridge(())
    assert not is_structural_table_bridge(("", "   "))


def test_more_than_six_bridge_lines_is_not_a_bridge() -> None:
    assert not is_structural_table_bridge(tuple(f"Row {i}" for i in range(7)))


# --- structural tail -------------------------------------------------------


def test_a_total_row_with_a_separator_above_is_a_tail() -> None:
    assert is_structural_table_tail(
        ("==========  ==========", "Total                    $3,250     $3,080")
    )


def test_a_total_row_recognised_by_the_caller_is_a_tail() -> None:
    assert is_structural_table_tail(
        ("Total liabilities and stockholders' deficit  100  90",),
        is_tail_line=_tail_line,
    )


def test_a_total_row_without_a_separator_needs_the_caller_predicate() -> None:
    line = "Total liabilities and stockholders' deficit  100  90"
    assert not is_structural_table_tail((line,))
    assert is_structural_table_tail((line,), is_tail_line=_tail_line)


def test_a_generic_total_word_is_not_a_tail() -> None:
    assert not is_structural_table_tail(("Total commentary follows",))


def test_an_empty_tail_is_not_a_tail() -> None:
    assert not is_structural_table_tail(())
    assert not is_structural_table_tail(("", "   "))


def test_a_separator_alone_is_not_a_tail() -> None:
    assert not is_structural_table_tail(("==========  ==========",))


def test_a_single_numeric_row_is_not_a_separator_tail() -> None:
    assert not is_structural_table_tail(("Cash                         100        90",))
