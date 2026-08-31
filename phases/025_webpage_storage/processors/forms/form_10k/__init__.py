"""Form 10-K family evaluators, cover preprocessors, and normalizers."""

from __future__ import annotations

from .evaluator import Form10KEvaluator
from .normalizer import Form10KNormalizer

__all__ = [
    "Form10KEvaluator",
    "Form10KNormalizer",
]
