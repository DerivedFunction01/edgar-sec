"""Tests for S10 content role evaluator stub."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.boundary.detector import CoverBoundary, BoundaryMethod
from edgar_sec.engine.forms.cover.checkmarks.solver import (
    CoverCheckmarkResult,
    InferenceStatus,
)
from edgar_sec.engine.forms.normalize import NormalizationResult
from edgar_sec.engine.forms.plugins.evaluators.content_role import (
    evaluate_document_role,
)


def test_evaluate_document_role_returns_none():
    """The stub evaluator always returns None."""
    result = evaluate_document_role(
        text="Sample text",
        expected_form="10-K",
        expected_role="primary",
    )
    assert result is None


def test_evaluate_document_role_with_normalization_result():
    """The stub accepts normalization_result but ignores it."""
    result = evaluate_document_role(
        text="Sample text",
        expected_form="10-K",
        expected_role="exhibit",
        normalization_result=None,
    )
    assert result is None


def test_evaluate_document_role_with_valid_normalization_result():
    """The stub accepts a valid NormalizationResult."""
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
    assert result is None
