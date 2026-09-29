"""Tests for the shared evaluator input contract."""

from __future__ import annotations

from edgar_sec.domain.forms.decisions import DecisionAction
from edgar_sec.engine.forms.evaluators.base import (
    ASCII_SIZE_CEILING,
    HTML_SIZE_CEILING,
    XBRL_MANDATE_YEAR,
    EvaluatorInput,
    proceed,
    refetch_exhibit,
)


def test_coerce_passes_through_an_input() -> None:
    data = EvaluatorInput(text="body", filing_year=2015)
    assert EvaluatorInput.coerce(data) is data


def test_coerce_wraps_a_bare_string() -> None:
    data = EvaluatorInput.coerce("body")
    assert data.text == "body"
    assert data.raw_text == "body"
    assert data.has_html_tags is False


def test_body_text_prefers_cleaned_text() -> None:
    assert EvaluatorInput(text="clean", raw_text="raw").body_text == "clean"
    assert EvaluatorInput(text="", raw_text="raw").body_text == "raw"


def test_xbrl_era_detection() -> None:
    assert EvaluatorInput(text="", filing_year=XBRL_MANDATE_YEAR).is_post_xbrl
    assert EvaluatorInput(text="", filing_year=2013).is_post_xbrl
    assert not EvaluatorInput(text="", filing_year=2011).is_post_xbrl
    assert not EvaluatorInput(text="", filing_year=None).is_post_xbrl


def test_size_ceiling_depends_on_representation() -> None:
    html = EvaluatorInput(
        text="", raw_text="x" * (HTML_SIZE_CEILING + 1), has_html_tags=True
    )
    assert html.above_size_ceiling is True
    ascii_large = EvaluatorInput(text="", raw_text="x" * (ASCII_SIZE_CEILING + 1))
    assert ascii_large.above_size_ceiling is True
    small = EvaluatorInput(text="", raw_text="x" * 10)
    assert small.above_size_ceiling is False


def test_proceed_decision_shape() -> None:
    decision = proceed("because", "category_name")
    assert decision.action == DecisionAction.PROCEED
    assert decision.target_exhibit is None
    assert decision.is_stub is False
    assert decision.category == "category_name"
    assert decision.reason == "because"


def test_refetch_decision_shape() -> None:
    decision = refetch_exhibit("EX-13", "why", "cat", line_number=7)
    assert decision.action == DecisionAction.REFETCH_SUB_DOC
    assert decision.target_exhibit == "EX-13"
    assert decision.is_stub is True
    assert decision.metadata == {"line_number": 7}
