"""Typed evidence packs for cover and body processing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CoverEvidencePack:
    """Evidence for cover-start and cover-end detection."""

    identity_terms: tuple[str, ...]
    shape_terms: tuple[str, ...]
    labels: tuple[str, ...]
    cover_end_terms: tuple[str, ...] = ()
    healing_rules: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class BodyEvidencePack:
    """Evidence for body-anchor detection and BoW scoring."""

    structural_headings: tuple[str, ...] = ()
    semantic_headings: tuple[str, ...] = ()
    body_ngrams: tuple[str, ...] = ()
    body_verbs: tuple[str, ...] = ()


__all__ = [
    "BodyEvidencePack",
    "CoverEvidencePack",
]
