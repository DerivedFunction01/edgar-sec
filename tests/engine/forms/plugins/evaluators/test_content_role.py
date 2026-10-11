"""Tests for S10 content role evaluator stub."""

from __future__ import annotations

from edgar_sec.domain.forms.common.exhibits import DocumentRoleAssessment
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
