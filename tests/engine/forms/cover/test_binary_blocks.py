"""Unit tests for binary Yes/No block merging and mark classification."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.binary_blocks import (
    classify_mark_line,
    merge_yes_no_binary_blocks,
    normalize_checkbox_tokens,
    strip_boxdot_spacers,
)


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
    merged = merge_yes_no_binary_blocks(lines, scope="cover_context")
    assert merged[1].endswith("No [ ] Yes [X]")


def test_merge_yes_no_binary_blocks_no_false_merge() -> None:
    lines = ["Yes", "we have filed all reports", "No", "further comment."]
    merged = merge_yes_no_binary_blocks(lines)
    # "we have filed..." is prose, not a checkbox mark -> no merge
    assert merged == lines


def test_bare_mark_canonicalization() -> None:
    assert normalize_checkbox_tokens("Yes x No o") == "Yes [X] No o"
    assert normalize_checkbox_tokens("Yes x No o", scope="cover_context") == (
        "Yes [X] No [ ]"
    )
    assert normalize_checkbox_tokens("X") == "[X]"
    assert normalize_checkbox_tokens("o") == "o"
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
    assert classify_mark_line("o") == "unknown"
    assert classify_mark_line("o", scope="cover_context") == "unchecked"
    assert classify_mark_line("R", context="gap") == "unknown"
    assert classify_mark_line("hello") == "unknown"
    assert classify_mark_line("x ANNUAL REPORT", context="leading") == "checked"
    assert classify_mark_line("Xylophone data", context="leading") == "unknown"


def test_merge_yes_no_binary_blocks_consolidated() -> None:
    # Case 1: 3-line Yes [ ] No x
    lines = ["...Securities Act. Yes", "[ ]", "No", "x", "next"]
    assert merge_yes_no_binary_blocks(lines)[0] == "...Securities Act. Yes [ ] No [X]"

    # Case 2: 4-line with blank
    lines = ["...Act. Yes", "o", "", "No", "next"]
    assert (
        merge_yes_no_binary_blocks(lines, scope="cover_context")[0]
        == "...Act. Yes [ ] No"
    )

    # Case 3: 5-line with blanks around mark
    lines = ["...Act. Yes", "", "o", "", "No", "next"]
    assert (
        merge_yes_no_binary_blocks(lines, scope="cover_context")[0]
        == "...Act. Yes [ ] No"
    )

    # Case 4: box+dot stripped
    lines = ["...Act. Yes", ".", "No", "next"]
    assert merge_yes_no_binary_blocks(lines)[0] == "...Act. Yes No"

    # Case 5: Wingdings single-char
    lines = ["...Act. Yes", "R", "No", "next"]
    assert merge_yes_no_binary_blocks(lines)[0] == "...Act. Yes"

    # Case 6: inverse order (No first)
    lines = ["...Act. No", "o", "Yes", "[X]", "next"]
    assert (
        merge_yes_no_binary_blocks(lines, scope="cover_context")[0]
        == "...Act. No [ ] Yes [X]"
    )

    # Case 7: prose gap = NOT merged
    lines = ["...Act. Yes", "some prose text", "No", "next"]
    result = merge_yes_no_binary_blocks(lines)
    assert result == lines

    # Inline prefix/suffix stays single line and gets canonicalized
    lines = ["[x] Yes ... No [ ]", "next"]
    result = merge_yes_no_binary_blocks(lines)
    assert result[0] == "[X] Yes ... No [ ]"
