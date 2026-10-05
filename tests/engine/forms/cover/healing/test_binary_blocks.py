"""Contract tests for binary Yes/No block merging."""

from __future__ import annotations

from edgar_sec.domain.forms.common.checkmarks import CheckmarkScope
from edgar_sec.engine.forms.cover.healing.binary_blocks import (
    classify_mark_line,
    merge_yes_no_binary_blocks,
    normalize_checkbox_tokens,
)


def test_a_box_slash_mark_becomes_the_canonical_unchecked_token() -> None:
    assert normalize_checkbox_tokens("Yes /   /") == "Yes [ ]"


def test_an_underscore_run_is_not_a_token_on_its_own() -> None:
    assert normalize_checkbox_tokens("Yes ____ No") == "Yes ____ No"
    assert normalize_checkbox_tokens("Yes __ unselected") == "Yes __ unselected"


def test_a_braced_mark_becomes_the_canonical_unchecked_token() -> None:
    assert normalize_checkbox_tokens("Yes { }") == "Yes [ ]"
    assert normalize_checkbox_tokens("Yes (_)") == "Yes [ ]"


def test_ascii_blank_and_braced_marks_are_unchecked() -> None:
    assert normalize_checkbox_tokens("Yes /   /") == "Yes [ ]"
    assert normalize_checkbox_tokens("Yes { }") == "Yes [ ]"


def test_bare_x_is_a_checked_token() -> None:
    assert normalize_checkbox_tokens("Yes x") == "Yes [X]"


def test_a_checked_context_glyph_is_normalized_in_both_scopes() -> None:
    assert normalize_checkbox_tokens("Yes \u25cf") == "Yes \u25cf"
    assert (
        normalize_checkbox_tokens("Yes \u25cf", scope=CheckmarkScope.COVER_CONTEXT)
        == "Yes [X]"
    )


def test_canonical_token_is_separated_from_adjacent_words() -> None:
    assert normalize_checkbox_tokens("[X]Annual") == "[X] Annual"
    assert normalize_checkbox_tokens("company[X]") == "company [X]"


def test_classify_mark_line_reads_a_full_line_mark() -> None:
    assert classify_mark_line("[X]") == "checked"
    assert classify_mark_line("[ ]") == "unchecked"
    assert classify_mark_line("") == "unknown"


def test_classify_mark_line_reads_a_leading_mark_before_a_capitalized_phrase() -> None:
    assert classify_mark_line("x ANNUAL REPORT", context="leading") == "checked"
    assert classify_mark_line("x annual report", context="leading") == "unknown"


def test_a_binary_block_collapses_onto_one_canonical_line() -> None:
    lines = ["Yes", "[X]", "No", "[ ]"]

    assert merge_yes_no_binary_blocks(lines) == ["Yes [X] No [ ]"]


def test_a_box_and_dot_spacer_is_stripped_from_the_block() -> None:
    lines = ["Yes", "[X]", ".", "No", "[ ]"]

    assert merge_yes_no_binary_blocks(lines) == ["Yes [X] No [ ]"]


def test_a_separator_line_between_marks_breaks_the_block() -> None:
    lines = ["Yes", "__X__", "---  ---", "No", "____"]

    assert merge_yes_no_binary_blocks(lines) == [
        normalize_checkbox_tokens(line) for line in lines
    ]


def test_inverse_word_order_is_recognized() -> None:
    lines = ["No", "[ ]", "Yes", "[X]"]

    assert merge_yes_no_binary_blocks(lines) == ["No [ ] Yes [X]"]


def test_a_bare_bullet_is_not_evidence_of_a_binary_block() -> None:
    lines = ["Yes", "o", "*", "No"]

    assert merge_yes_no_binary_blocks(lines) == [
        normalize_checkbox_tokens(line) for line in lines
    ]


def test_a_single_tail_word_is_not_a_binary_block() -> None:
    lines = ["Yes", "[X]", "continues onto the next page"]

    assert merge_yes_no_binary_blocks(lines) == [
        normalize_checkbox_tokens(line) for line in lines
    ]


def test_merging_leaves_ordinary_lines_untouched() -> None:
    lines = ["FORM 10-K", "", "PART I"]

    assert merge_yes_no_binary_blocks(lines) == lines


def test_wrapped_slash_and_pipe_marks_abutting_words_normalize_and_space() -> None:
    assert normalize_checkbox_tokens("/ x /Annual") == "[X] Annual"
    assert normalize_checkbox_tokens("or /  /Transition") == "or [ ] Transition"
    assert normalize_checkbox_tokens("| x |Annual") == "[X] Annual"
    assert normalize_checkbox_tokens(r"\ x \Annual") == "[X] Annual"
    assert normalize_checkbox_tokens("{x}Annual") == "[X] Annual"
    assert normalize_checkbox_tokens("or[X]Annual") == "or [X] Annual"


def test_adversarial_paths_and_urls_are_not_corrupted() -> None:
    assert (
        normalize_checkbox_tokens("http://example.com/x/annual")
        == "http://example.com/x/annual"
    )
    assert (
        normalize_checkbox_tokens("from 12/31/1998 to 12/31/1999")
        == "from 12/31/1998 to 12/31/1999"
    )
