"""S10 content role evaluator stub for D0 contract freeze."""

from __future__ import annotations

from edgar_sec.domain.forms.common.exhibits import DocumentRoleAssessment


def evaluate_document_role(
    text: str,
    *,
    expected_form: str,
    expected_role: str,
    normalization_result: NormalizationResult | None = None,
) -> DocumentRoleAssessment | None:
    """Stub evaluator that does no scanning and always returns None."""
    return None


__all__ = ["evaluate_document_role"]
