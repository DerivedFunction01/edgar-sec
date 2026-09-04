"""Generic multi-form taxonomy registry and matcher factory."""

from __future__ import annotations

import re
from typing import Any

from defs.text.automaton import LexicalMatcher, compile_lexical_matcher

_TAXONOMY_REGISTRY: dict[str, dict[str, Any]] = {}
_AGGREGATE_MATCHER: LexicalMatcher | None = None
_TAXONOMY_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _taxonomy_normalize(text: str) -> str:
    """Normalize text to the same canonical form as taxonomy keyword storage."""
    lowered = text.lower()
    sanitized = _TAXONOMY_NORMALIZE_RE.sub(" ", lowered)
    return " ".join(sanitized.split()).strip()


def _build_registry() -> None:
    if _TAXONOMY_REGISTRY:
        return
    from defs.sec_forms.forms.annual.taxonomy import FORM_10K_DERIVED, FORM_20F_DERIVED
    from defs.sec_forms.forms.current_report.taxonomy import FORM_8K_DERIVED
    from defs.sec_forms.forms.quarterly.taxonomy import FORM_10Q_DERIVED

    _TAXONOMY_REGISTRY["10-K"] = FORM_10K_DERIVED
    _TAXONOMY_REGISTRY["20-F"] = FORM_20F_DERIVED
    _TAXONOMY_REGISTRY["10-Q"] = FORM_10Q_DERIVED
    _TAXONOMY_REGISTRY["8-K"] = FORM_8K_DERIVED


def get_taxonomy(family: str | None) -> dict[str, Any] | None:
    if family is None:
        return None
    _build_registry()
    return _TAXONOMY_REGISTRY.get(family)


def get_taxonomy_matcher(family: str | None = None) -> LexicalMatcher:
    _build_registry()
    if family is not None:
        taxonomy = _TAXONOMY_REGISTRY.get(family)
        if taxonomy is not None:
            matcher = taxonomy.get("matcher")
            if matcher is not None:
                return matcher
    return _get_or_build_aggregate_matcher()


def _get_or_build_aggregate_matcher() -> LexicalMatcher:
    global _AGGREGATE_MATCHER
    if _AGGREGATE_MATCHER is None:
        _build_registry()
        all_keywords: list[str] = []
        for taxonomy in _TAXONOMY_REGISTRY.values():
            for key in ("norm_toc_keywords", "norm_early_names", "norm_late_names"):
                all_keywords.extend(
                    kw for kw in taxonomy.get(key, ()) if len(kw.split()) > 1
                )
        _AGGREGATE_MATCHER = compile_lexical_matcher(
            {"taxonomy_heading": tuple(all_keywords)}
        )
    return _AGGREGATE_MATCHER


__all__ = [
    "_taxonomy_normalize",
    "get_taxonomy",
    "get_taxonomy_matcher",
]
