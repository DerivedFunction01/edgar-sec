"""Tests for form-agnostic content role evaluator."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.boundary.detector import BoundaryMethod, CoverBoundary
from edgar_sec.engine.forms.cover.checkmarks.solver import (
    CoverCheckmarkResult,
    InferenceStatus,
)
from edgar_sec.engine.forms.normalize import NormalizationResult
from edgar_sec.engine.forms.plugins.evaluators.content_role import (
    evaluate_document_role,
)


def test_scope_gate_returns_none_for_unsupported_form():
    """Evaluator returns None for forms without registered profiles."""
    result = evaluate_document_role(
        text="Sample text",
        expected_form="4",
        expected_role="primary",
    )
    assert result is None

    result = evaluate_document_role(
        text="Sample text",
        expected_form="6-K",
        expected_role="primary",
    )
    assert result is None


def test_consistent_10k_primary():
    """10-K text with 10-K title returns consistent."""
    text = (
        "ANNUAL REPORT ON FORM 10-K\n"
        "For the fiscal year ended December 31, 2024\n"
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
        "Washington, D.C. 20549"
    )
    result = evaluate_document_role(
        text=text,
        expected_form="10-K",
        expected_role="primary",
    )
    assert result is not None
    assert result.disposition == "consistent"
    assert result.observed_kind == "primary_report"


def test_consistent_10q_primary():
    """10-Q text with 10-Q title returns consistent."""
    text = (
        "QUARTERLY REPORT ON FORM 10-Q\n"
        "For the quarterly period ended March 31, 2024\n"
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
        "Washington, D.C. 20549"
    )
    result = evaluate_document_role(
        text=text,
        expected_form="10-Q",
        expected_role="primary",
    )
    assert result is not None
    assert result.disposition == "consistent"
    assert result.observed_kind == "primary_report"


def test_consistent_8k_primary():
    """8-K text with 8-K title returns consistent."""
    text = (
        "CURRENT REPORT ON FORM 8-K\n"
        "Item 1.01 Entry into a Material Definitive Agreement\n"
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
        "Washington, D.C. 20549"
    )
    result = evaluate_document_role(
        text=text,
        expected_form="8-K",
        expected_role="primary",
    )
    assert result is not None
    assert result.disposition == "consistent"
    assert result.observed_kind == "primary_report"


def test_form_mismatch():
    """Document expected to be 10-K containing 10-Q title."""
    text = (
        "QUARTERLY REPORT ON FORM 10-Q\n"
        "For the quarterly period ended March 31, 2024\n"
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
        "Washington, D.C. 20549"
    )
    result = evaluate_document_role(
        text=text,
        expected_form="10-K",
        expected_role="primary",
    )
    assert result is not None
    assert result.disposition == "possible_role_mismatch"
    assert result.observed_kind == "primary_report"


def test_insufficient_evidence():
    """Blank or arbitrary prose text returns insufficient_evidence."""
    text = "This is just some random text that doesn't match any form pattern."
    result = evaluate_document_role(
        text=text,
        expected_form="10-K",
        expected_role="primary",
    )
    assert result is not None
    assert result.disposition == "insufficient_evidence"
    assert result.observed_kind == "unknown"


def test_normalization_result_passed():
    """Evaluator accepts NormalizationResult parameter."""
    norm_result = NormalizationResult(
        text="Sample text",
        family="10-K",
        representation="ascii",
        cover_boundary=CoverBoundary(
            end_line=50,
            end_offset=500,
            method=BoundaryMethod.STRUCTURAL,
            confidence=0.9,
            approximate=False,
        ),
        cover_checkmarks=CoverCheckmarkResult(
            status=InferenceStatus.RESOLVED,
        ),
    )
    result = evaluate_document_role(
        text="Sample text",
        expected_form="10-K",
        expected_role="primary",
        normalization_result=norm_result,
    )
    # With minimal text, should return insufficient_evidence
    assert result is not None
