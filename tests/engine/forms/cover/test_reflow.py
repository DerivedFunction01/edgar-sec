"""Contract tests for cover layout policies supplied to the reflow engine."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.reflow import (
    is_checkbox_answer_line,
    is_cover_layout_line,
)


def test_yes_no_line_with_a_mark_is_a_checkbox_answer() -> None:
    assert is_checkbox_answer_line("Yes [X] No [ ]") is True


def test_yes_no_line_without_a_mark_is_not_a_checkbox_answer() -> None:
    assert is_checkbox_answer_line("Yes No") is False


def test_marked_line_without_yes_no_grammar_is_not_a_checkbox_answer() -> None:
    assert is_checkbox_answer_line("[X] ANNUAL REPORT") is False


def test_exact_headings_are_cover_layout() -> None:
    assert is_cover_layout_line("PART I") is True
    assert is_cover_layout_line("ITEM 1. BUSINESS") is True
    assert is_cover_layout_line("TABLE OF CONTENTS") is True


def test_short_form_declaration_lines_are_cover_layout() -> None:
    assert is_cover_layout_line("FORM 10-K") is True
    assert is_cover_layout_line("  Form 10-Q  ") is True


def test_registrant_and_filer_fields_are_cover_layout() -> None:
    assert (
        is_cover_layout_line("Precise name of registrant as specified in Section 10(b)")
        is True
    )
    assert is_cover_layout_line("Commission File Number 001-12345") is True
    assert (
        is_cover_layout_line(
            "Securities registered pursuant to Section 12(b) of the Act"
        )
        is True
    )
    assert is_cover_layout_line("Washington, D.C. 20549") is False


def test_body_prose_is_not_cover_layout() -> None:
    assert is_cover_layout_line("") is False
    assert is_cover_layout_line("   ") is False
    assert is_cover_layout_line("The company operates worldwide.") is False


def test_results_are_memoized_per_line() -> None:
    assert is_cover_layout_line("FORM 10-K") is True
    assert is_cover_layout_line("FORM 10-K") is True
