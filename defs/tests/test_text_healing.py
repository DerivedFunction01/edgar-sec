"""Unit and contract tests for defs.text.healing."""

from __future__ import annotations

from defs.sec_forms.forms.annual import ANNUAL_ADDITIONAL_PHRASE_RULES
from defs.sec_forms.sequences import COMMON_PHRASE_RULES
from defs.text.healing import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
    PhraseSequenceRule,
    classify_mark_line,
    heal_split_lines,
    merge_yes_no_binary_blocks,
    normalize_checkbox_tokens,
    normalize_whitespace_and_tabs,
    should_join_two_lines,
    strip_boxdot_spacers,
)


def test_normalize_whitespace_and_tabs() -> None:
    raw = "UNITED\t\tSTATES\r\n\t  \t\r\nSECURITIES   AND   EXCHANGE   COMMISSION\n\n\nWASHINGTON, D.C."
    cleaned = normalize_whitespace_and_tabs(raw)
    expected = "UNITED STATES\n\nSECURITIES AND EXCHANGE COMMISSION\n\nWASHINGTON, D.C."
    assert cleaned == expected


def test_normalize_checkbox_tokens() -> None:
    raw = "Large accelerated filer ☒ Non-accelerated filer ☐ Shell company þ [x] [ ] &#9746; &#9744;"
    normalized = normalize_checkbox_tokens(raw)
    assert CANONICAL_CHECKED in normalized
    assert CANONICAL_UNCHECKED in normalized
    assert "☒" not in normalized
    assert "☐" not in normalized
    assert "þ" not in normalized


def test_should_join_two_lines_and_negative_guards() -> None:
    rules = [
        PhraseSequenceRule(
            name="sec_agency",
            tokens=["united", "states", "securities", "and", "exchange", "commission"],
            anchor=["united", "securities", "commission"],
        ),
        PhraseSequenceRule(
            name="fiscal_period",
            tokens=["for", "the", "fiscal", "year", "ended"],
            anchor=["fiscal"],
        ),
    ]

    # Positive joins
    assert (
        should_join_two_lines(
            "UNITED STATES", "SECURITIES AND EXCHANGE COMMISSION", rules
        )
        is True
    )
    assert (
        should_join_two_lines("For the fiscal", "year ended December 31, 2024", rules)
        is True
    )

    # Negative boundary guards
    assert (
        should_join_two_lines("Common Stock", "(1) has filed all reports", rules)
        is False
    )
    assert (
        should_join_two_lines("Securities", "[X] ANNUAL REPORT PURSUANT", rules)
        is False
    )
    assert should_join_two_lines("Address", "<TABLE>", rules) is False

    # Caption vs value separation
    assert (
        should_join_two_lines(
            "270 Park Avenue", "(Address of Principal Executive Offices)", rules
        )
        is False
    )


def test_heal_split_lines_end_to_end() -> None:
    rules = [
        PhraseSequenceRule(
            name="sec_banner",
            tokens=["united", "states", "securities", "and", "exchange", "commission"],
            anchor=["securities"],
        ),
        PhraseSequenceRule(
            name="fiscal_period",
            tokens=["for", "the", "fiscal", "year", "ended"],
            anchor=["fiscal"],
        ),
    ]

    lines = [
        "UNITED STATES",
        "SECURITIES AND EXCHANGE COMMISSION",
        "WASHINGTON, D.C. 20549",
        "FORM 10-K",
        "For the fiscal",
        "year ended December 31, 2024",
        "[X] ANNUAL REPORT PURSUANT TO SECTION 13",
    ]

    healed = heal_split_lines(lines, rules)
    assert healed[0] == "UNITED STATES SECURITIES AND EXCHANGE COMMISSION"
    assert healed[1] == "WASHINGTON, D.C. 20549"
    assert healed[2] == "FORM 10-K"
    assert healed[3] == "For the fiscal year ended December 31, 2024"
    assert healed[4] == "[X] ANNUAL REPORT PURSUANT TO SECTION 13"


def test_merge_yes_no_binary_blocks_standard() -> None:
    lines = [
        "Indicate by check mark if the registrant is a well-known seasoned issuer.",
        "Yes",
        "[ ]",
        "No",
        "x",
        "Some other question.",
    ]
    merged = merge_yes_no_binary_blocks(lines)
    assert (
        "Indicate by check mark if the registrant is a well-known seasoned issuer."
        in merged[0]
    )
    assert merged[1].endswith("Yes [ ] No [X]")
    assert merged[2] == "Some other question."


def test_merge_yes_no_binary_blocks_inverse_and_bare_marks() -> None:
    lines = ["Is the registrant a shell company?", "No", "o", "Yes", "[X]", "Done."]
    merged = merge_yes_no_binary_blocks(lines)
    assert merged[1].endswith("No [ ] Yes [X]")


def test_merge_yes_no_binary_blocks_no_false_merge() -> None:
    lines = ["Yes", "we have filed all reports", "No", "further comment."]
    merged = merge_yes_no_binary_blocks(lines)
    # "we have filed..." is prose, not a checkbox mark -> no merge
    assert merged == lines


def test_bare_mark_canonicalization() -> None:
    assert normalize_checkbox_tokens("Yes x No o") == "Yes [X] No [ ]"
    assert normalize_checkbox_tokens("X") == "[X]"
    assert normalize_checkbox_tokens("o") == "[ ]"
    # must not touch letters inside words
    assert normalize_checkbox_tokens("x-ray") == "x-ray"
    assert normalize_checkbox_tokens("box") == "box"
    assert normalize_checkbox_tokens("max") == "max"


def test_strip_boxdot_spacers() -> None:
    lines = ["Yes", ".", "No", "x", "after"]
    assert strip_boxdot_spacers(lines) == ["Yes", "No", "x", "after"]


def test_classify_mark_line_recognized() -> None:

    assert classify_mark_line("[X]") == "checked"
    assert classify_mark_line("[ ]") == "unchecked"
    assert classify_mark_line("x") == "checked"
    assert classify_mark_line("o") == "unchecked"
    assert classify_mark_line("R", context="gap") == "unchecked"
    assert classify_mark_line("hello") == "unknown"
    assert classify_mark_line("x ANNUAL REPORT", context="leading") == "checked"
    assert classify_mark_line("Xylophone data", context="leading") == "unknown"


def test_merge_yes_no_binary_blocks_consolidated() -> None:
    from defs.text.healing import merge_yes_no_binary_blocks

    # Case 1: 3-line Yes [ ] No x
    lines = ["...Securities Act. Yes", "[ ]", "No", "x", "next"]
    assert merge_yes_no_binary_blocks(lines)[0] == "...Securities Act. Yes [ ] No [X]"

    # Case 2: 4-line with blank
    lines = ["...Act. Yes", "o", "", "No", "next"]
    assert merge_yes_no_binary_blocks(lines)[0] == "...Act. Yes [ ] No"

    # Case 3: 5-line with blanks around mark
    lines = ["...Act. Yes", "", "o", "", "No", "next"]
    assert merge_yes_no_binary_blocks(lines)[0] == "...Act. Yes [ ] No"

    # Case 4: box+dot stripped (mark is invisible inside bordered box)
    lines = ["...Act. Yes", ".", "No", "next"]
    assert merge_yes_no_binary_blocks(lines)[0] == "...Act. Yes No"

    # Case 5: Wingdings single-char
    lines = ["...Act. Yes", "R", "No", "next"]
    assert merge_yes_no_binary_blocks(lines)[0] == "...Act. Yes [ ] No"

    # Case 7: inverse order (No first)
    lines = ["...Act. No", "o", "Yes", "[X]", "next"]
    assert merge_yes_no_binary_blocks(lines)[0] == "...Act. No [ ] Yes [X]"

    # Case 8: prose gap = NOT merged
    lines = ["...Act. Yes", "some prose text", "No", "next"]
    result = merge_yes_no_binary_blocks(lines)
    assert result == lines

    # Inline prefix/suffix stays single line and gets canonicalized
    lines = ["[x] Yes ... No [ ]", "next"]
    result = merge_yes_no_binary_blocks(lines)
    assert result[0] == "[X] Yes ... No [ ]"
    lines = [
        "Indicate the number of shares outstanding",
        "of each of the registrant's classes of common stock",
        "as of January 31, 2025: 15,115,823,000 shares.",
        "The aggregate market value of the voting and",
        "non-voting common equity held by non-affiliates",
        "of the registrant was approximately $3,000,000,000.",
        "Documents incorporated",
        "by reference: Portions of Part III.",
    ]

    rules = tuple(COMMON_PHRASE_RULES) + tuple(ANNUAL_ADDITIONAL_PHRASE_RULES)
    healed = heal_split_lines(lines, rules)
    assert (
        "Indicate the number of shares outstanding of each of the registrant's classes of common stock as of January 31, 2025: 15,115,823,000 shares."
        in healed[0]
    )
    assert (
        "The aggregate market value of the voting and non-voting common equity held by non-affiliates of the registrant was approximately $3,000,000,000."
        in healed[1]
    )
    assert "Documents incorporated by reference: Portions of Part III." in healed[2]
