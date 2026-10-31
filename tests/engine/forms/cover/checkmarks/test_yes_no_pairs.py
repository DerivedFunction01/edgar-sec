"""Contract tests for inline Yes/No pair normalization."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.checkmarks.yes_no_pairs import (
    YES_NO_LINE_RE,
    YES_NO_WORD_RE,
    normalize_yes_no_pair_line,
    normalize_yes_no_pairs,
)


def test_word_and_line_expressions_capture_both_answers() -> None:
    assert YES_NO_WORD_RE.search("Yes [X]").group("answer") == "Yes"
    assert YES_NO_LINE_RE.search("Yes [X] No [ ]") is not None


def test_a_pair_with_marks_before_the_answers_is_canonicalized() -> None:
    assert normalize_yes_no_pair_line("[X] Yes No____") == "[X] Yes No [ ]"


def test_a_pair_with_marks_after_the_answers_is_canonicalized() -> None:
    assert normalize_yes_no_pair_line("Yes ____ No /X/") == "Yes [ ] No [X]"


def test_a_line_without_both_answers_is_untouched() -> None:
    assert normalize_yes_no_pair_line("Yes [X]") == "Yes [X]"
    assert normalize_yes_no_pair_line("") == ""


def test_multiple_pairs_on_one_line_are_canonicalized_together() -> None:
    assert (
        normalize_yes_no_pair_line("Yes __X__ No _____ Yes _____ No __X__")
        == "Yes [X] No [ ] Yes [ ] No [X]"
    )


def test_a_line_slice_is_bounded_to_the_requested_range() -> None:
    text = "FORM 10-K\nYes [X] No [ ]\n"

    rewritten, changed = normalize_yes_no_pairs(text, start_line=1, end_line=2)
    assert rewritten == "FORM 10-K\nYes [X] No [ ]\n"
    assert changed is False

    rewritten, changed = normalize_yes_no_pairs(text, start_line=1)
    assert changed is False


def test_a_slice_beyond_the_document_is_clamped() -> None:
    text = "Yes [X] No [ ]\n"

    rewritten, changed = normalize_yes_no_pairs(text, end_line=99)

    assert rewritten == "Yes [X] No [ ]\n"
    assert changed is False


def test_a_changed_slice_is_reported() -> None:
    text = "FORM 10-K\nYes __X__ No _____\n"

    rewritten, changed = normalize_yes_no_pairs(text)

    assert changed is True
    assert rewritten == "FORM 10-K\nYes [X] No [ ]\n"


def test_parenthesized_and_braced_yes_no_pairs_are_canonicalized() -> None:
    assert normalize_yes_no_pair_line("Yes (x) No ( )") == "Yes [X] No [ ]"
    assert normalize_yes_no_pair_line("Yes (X) No (  )") == "Yes [X] No [ ]"
    assert normalize_yes_no_pair_line("Yes {x} No { }") == "Yes [X] No [ ]"


def test_multi_spaced_bracket_yes_no_pairs_are_canonicalized() -> None:
    assert normalize_yes_no_pair_line("Yes [ x ] No [  ]") == "Yes [X] No [ ]"


def test_adversarial_numbers_and_area_codes_do_not_falsely_normalize() -> None:
    prose = "Section 13 or 15(d) of the Exchange Act\nTelephone: (555) 123-4567\n"
    rewritten, changed = normalize_yes_no_pairs(prose)
    assert rewritten == prose
    assert changed is False

    numbered = "(1) Yes [X] No [ ] (2) Yes [ ] No [X]\n"
    rewritten, changed = normalize_yes_no_pairs(numbered)
    assert "(1) Yes [X] No [ ] (2) Yes [ ] No [X]" in rewritten
