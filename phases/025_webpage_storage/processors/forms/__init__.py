"""Form evaluators and normalizers package for Phase 025 document processing."""

from __future__ import annotations

from .base import (
    CoverPreprocessResult,
    DecisionAction,
    FormEvaluator,
    FormNormalizer,
    PreprocessedDocument,
    RefetchDecision,
)
from .form_8k import (
    Form8KEvaluator,
    Form8KNormalizer,
)
from .form_10k import (
    Form10KEvaluator,
    Form10KNormalizer,
)
from .form_10q import (
    Form10QEvaluator,
    Form10QNormalizer,
)
from .form_generic import GenericFormEvaluator, GenericFormNormalizer

__all__ = [
    "CoverPreprocessResult",
    "DecisionAction",
    "Form8KEvaluator",
    "Form8KNormalizer",
    "Form10KEvaluator",
    "Form10KNormalizer",
    "Form10QEvaluator",
    "Form10QNormalizer",
    "FormEvaluator",
    "FormNormalizer",
    "GenericFormEvaluator",
    "GenericFormNormalizer",
    "PreprocessedDocument",
    "RefetchDecision",
]
