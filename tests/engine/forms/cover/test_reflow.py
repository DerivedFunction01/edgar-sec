"""Unit tests for cover-specific reflow policies."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.reflow import (
    is_checkbox_answer_line,
    is_cover_layout_line,
    is_page_marker_line,
)


def test_is_cover_layout_line() -> None:
    assert is_cover_layout_line("EXACT NAME OF REGISTRANT AS SPECIFIED IN ITS CHARTER")
    assert is_cover_layout_line(
        "State or other jurisdiction of incorporation: Delaware"
    )
    assert is_cover_layout_line("Commission file number: 001-12345")
    assert is_cover_layout_line("Address of Principal Executive Offices: 123 Main St")
    assert is_cover_layout_line("Title of each class: Common Stock, $0.01 par value")
    assert is_cover_layout_line("FORM 10-K")
    assert is_cover_layout_line("TABLE OF CONTENTS")
    assert is_cover_layout_line("PART I")
    assert not is_cover_layout_line(
        "The company manufactures and sells specialty widgets."
    )


def test_is_checkbox_answer_line() -> None:
    assert is_checkbox_answer_line("Yes [X]   No [ ]")
    assert is_checkbox_answer_line("Yes [ ]   No [X]")
    assert not is_checkbox_answer_line("Yes No without mark")
    assert not is_checkbox_answer_line("General prose discussing yes or no outcomes")


def test_is_page_marker_line() -> None:
    assert is_page_marker_line("Page 1 of 50")
    assert is_page_marker_line("- 12 -")
    assert is_page_marker_line("<PAGE>")
    assert not is_page_marker_line("Just a line of prose")
