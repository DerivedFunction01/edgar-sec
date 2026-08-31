"""Shared form-family preprocessing contracts and implementations."""

from .headers import (
    FORM_8K_GRAMMAR,
    FORM_10K_GRAMMAR,
    FORM_10Q_GRAMMAR,
    HeaderGrammar,
    HeaderMatch,
    make_grammar,
    match_header,
    normalize_headers,
)
from .hybrid_cover import CoverPreprocessResult, HybridCoverPreprocessor

__all__ = [
    "FORM_8K_GRAMMAR",
    "FORM_10K_GRAMMAR",
    "FORM_10Q_GRAMMAR",
    "CoverPreprocessResult",
    "HeaderGrammar",
    "HeaderMatch",
    "HybridCoverPreprocessor",
    "make_grammar",
    "match_header",
    "normalize_headers",
]
