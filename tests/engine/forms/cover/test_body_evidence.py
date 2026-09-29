"""Tests for body-prose lexical scoring."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.body_evidence import (
    MIN_BODY_SCORE,
    build_body_matcher,
    describe_score,
    is_body_prose,
    is_semantic_heading,
    score_body_text,
    score_confidence,
)

NARRATIVE = (
    "The Company was founded in 1994 and is a leading provider of widgets. "
    "It operates three manufacturing facilities and employs approximately "
    "4,200 people worldwide."
)


def test_narrative_prose_scores_decisive() -> None:
    assert score_body_text(NARRATIVE) >= MIN_BODY_SCORE
    assert is_body_prose(NARRATIVE) is True


def test_cover_field_list_is_not_body_prose() -> None:
    cover = (
        "ACME INDUSTRIAL WIDGETS, INC.\n"
        "Delaware\n"
        "Commission File Number: 001-14103\n"
        "1234 Widget Parkway, Springfield, IL 62704\n"
        "Trading Symbol(s)\n"
        "ACMX\n"
    )
    assert score_body_text(cover) < MIN_BODY_SCORE
    assert is_body_prose(cover) is False


def test_strong_phrase_alone_is_decisive() -> None:
    assert score_body_text("management believes") == 3
    assert score_body_text("collective bargaining") == 3


def test_soft_phrases_need_breadth() -> None:
    assert score_body_text("safe harbor") < 3
    assert score_body_text("safe harbor and undue reliance") >= 2


def test_cover_exclusion_vetoes() -> None:
    text = (
        "The Company was founded in 1994 and employs approximately 4,200 "
        "people worldwide, and operates manufacturing facilities. "
        "Commission file number 001-14103"
    )
    assert score_body_text(text) == 0


def test_empty_text_scores_zero() -> None:
    assert score_body_text("") == 0
    assert score_body_text("   ") == 0


def test_semantic_heading_detection() -> None:
    assert is_semantic_heading("RISK FACTORS") is True
    assert is_semantic_heading("Management's Discussion and Analysis") is True
    assert is_semantic_heading("SIGNATURES") is False
    assert is_semantic_heading("") is False


def test_confidence_ladder() -> None:
    assert score_confidence(0) == 0.0
    assert score_confidence(1) == 0.5
    assert score_confidence(2) == 0.7
    assert score_confidence(3) == 0.85


def test_matcher_is_reusable() -> None:
    matcher = build_body_matcher()
    assert "body_prose" in matcher.categories
    assert matcher.has_any(NARRATIVE)


def test_describe_score_is_traceable() -> None:
    assert "3" in describe_score(3)
