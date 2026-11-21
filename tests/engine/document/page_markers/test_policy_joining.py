"""How a removal joins the text it interrupts."""

from __future__ import annotations

from edgar_sec.engine.document.page_markers.detector import analyze_page_markers
from edgar_sec.engine.document.page_markers.policy import apply_page_markers
from tests.engine.document.page_markers.policy_support import NO_TOC


def test_a_removal_inside_a_sentence_is_joined_with_a_space() -> None:
    text = "The company continues on page\n<PAGE> 2\nfor the year.\n"
    analysis = analyze_page_markers(text, NO_TOC)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "continues on page for the year." in result


def test_a_removal_after_a_terminal_character_is_not_joined() -> None:
    text = "A complete sentence.\n<PAGE> 2\nThe next sentence.\n"
    analysis = analyze_page_markers(text, NO_TOC)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "A complete sentence.\nThe next sentence." in result


def test_a_removal_is_not_joined_before_a_negative_boundary_phrase() -> None:
    # "none of" continues the sentence, so joining it would concatenate two halves.
    text = "The company reports on page\n<PAGE> 2\nnone of which changed.\n"
    analysis = analyze_page_markers(text, NO_TOC)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "reports on page none of which changed." in result
