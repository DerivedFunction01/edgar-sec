"""Tests for the shared mark canonicalization adapter."""

from __future__ import annotations

from edgar_sec.engine.forms.common.marks import (
    canonicalize_filled_marks,
    canonicalize_filled_marks_in_span,
    canonicalize_mark_tokens,
    mark_state_in,
)


def test_canonicalize_filled_marks_separates_the_label() -> None:
    assert canonicalize_filled_marks("___x____Director") == "[X] Director"
    assert canonicalize_filled_marks("___X____Annual") == "[X] Annual"
    assert canonicalize_filled_marks("Director___X___") == "Director [X]"


def test_canonicalize_filled_marks_leaves_an_unfilled_run() -> None:
    assert canonicalize_filled_marks("_______") == "_______"
    assert canonicalize_filled_marks("Name: ______") == "Name: ______"


def test_canonicalize_filled_marks_leaves_a_word_ending_in_x() -> None:
    assert canonicalize_filled_marks("tax___") == "tax___"
    assert canonicalize_filled_marks("Tax") == "Tax"


def test_canonicalize_filled_marks_in_span_limits_the_range() -> None:
    text = "___X____Annual\nbody ___X____ text\n"

    normalized, changed = canonicalize_filled_marks_in_span(
        text, start_line=0, end_line=1
    )

    assert changed is True
    assert normalized == "[X] Annual\nbody ___X____ text\n"


def test_canonicalize_filled_marks_in_span_reports_no_change() -> None:
    normalized, changed = canonicalize_filled_marks_in_span("plain text\n")

    assert changed is False
    assert normalized == "plain text\n"


def test_canonicalize_mark_tokens_uses_the_shared_state() -> None:
    assert canonicalize_mark_tokens("☒") == "[X]"
    assert canonicalize_mark_tokens("(x)") == "[X]"
    assert canonicalize_mark_tokens("☐") == "[ ]"


def test_canonicalize_mark_tokens_keeps_an_unfilled_run() -> None:
    assert canonicalize_mark_tokens("______") == "______"


def test_mark_state_in_reports_the_first_known_state() -> None:
    assert mark_state_in("___X____Annual") == "checked"
    assert mark_state_in("☐") == "unchecked"
    assert mark_state_in("______") is None
    assert mark_state_in("no mark here") is None
