"""Public exports for form-driven document normalization."""

from .base import FormNormalizationPipeline
from .engine import DocumentNormalizer, normalize_document
from .models import NormalizationResult
from .registry import get_pipeline, register_pipeline

__all__ = [
    "DocumentNormalizer",
    "FormNormalizationPipeline",
    "NormalizationResult",
    "get_pipeline",
    "normalize_document",
    "register_pipeline",
]
