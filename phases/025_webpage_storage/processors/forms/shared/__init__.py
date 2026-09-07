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

__all__ = [
    "FORM_8K_GRAMMAR",
    "FORM_10K_GRAMMAR",
    "FORM_10Q_GRAMMAR",
    "HeaderGrammar",
    "HeaderMatch",
    "make_grammar",
    "match_header",
    "normalize_headers",
]
