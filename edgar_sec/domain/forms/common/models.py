"""Typed evidence packs and profile models for form-family isolation.

Ported from v1 defs/sec_forms/forms/common.py and defs/sec_forms/cover/profiles.py.
Defines pure data contracts consumed by form plugins and engine boundary detection.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from edgar_sec.domain.forms.decisions import EvaluatorDecision
from edgar_sec.domain.forms.schemas import CoverCheckboxSchema
from edgar_sec.foundation.text.healing import PhraseSequenceRule

#: Content transformation hook for post-normalization rewrites.
ContentTransform = Callable[[str], str]

#: Form-level evaluator hook that triages normalized text.
Evaluator = Callable[[str], EvaluatorDecision]


@dataclass(frozen=True, slots=True)
class CoverEvidencePack:
    """Evidence vocabulary and rules for cover-start and cover-end detection."""

    identity_terms: tuple[str, ...]
    shape_terms: tuple[str, ...]
    labels: tuple[str, ...]
    cover_end_terms: tuple[str, ...] = ()
    healing_rules: tuple[PhraseSequenceRule, ...] = ()


@dataclass(frozen=True, slots=True)
class BodyEvidencePack:
    """Evidence for body-anchor detection, depth guards, and lexical scoring."""

    structural_headings: tuple[str, ...] = ()
    semantic_headings: tuple[str, ...] = ()
    body_ngrams: tuple[str, ...] = ()
    body_verbs: tuple[str, ...] = ()
    body_terms: tuple[str, ...] = ()
    cover_terms: tuple[str, ...] = ()
    lexical: Any | None = None


@dataclass(frozen=True, slots=True)
class CoverProfile:
    """Complete specification for a modeled SEC form family."""

    family: str
    boundary_enabled: bool = True
    cover_evidence: CoverEvidencePack | None = None
    body_evidence: BodyEvidencePack | None = None
    cover_schema: CoverCheckboxSchema | None = None
    healing_rules: tuple[PhraseSequenceRule, ...] = ()
    reflow_prose: bool = False
    clean_tables: bool = True
    merge_binary_blocks: bool = False
    enable_body_start: bool = True
    enable_closing_span: bool = True
    enable_toc: bool = True
    transform_content: ContentTransform | None = None
    evaluator: Evaluator | None = None


__all__ = [
    "BodyEvidencePack",
    "ContentTransform",
    "CoverEvidencePack",
    "CoverProfile",
    "Evaluator",
]
