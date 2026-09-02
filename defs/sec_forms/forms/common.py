"""Typed evidence packs for cover and body processing."""

from __future__ import annotations

from dataclasses import dataclass

from defs.text.bow import EvidenceTier, LexicalEvidencePack


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
    """Evidence for body-anchor detection and lexical scoring.

    ``structural_headings`` and ``semantic_headings`` are body-anchor
    metadata consumed by the body-start resolver. Lexical scoring consumes
    ``lexical``; the flat ``body_*`` fields are legacy vocabulary retained
    for compiled-rule derivation when no explicit pack is supplied.
    """

    structural_headings: tuple[str, ...] = ()
    semantic_headings: tuple[str, ...] = ()
    body_ngrams: tuple[str, ...] = ()
    body_verbs: tuple[str, ...] = ()
    body_terms: tuple[str, ...] = ()
    cover_terms: tuple[str, ...] = ()
    lexical: LexicalEvidencePack | None = None


def derive_lexical_pack(
    *,
    body_ngrams: tuple[str, ...] = (),
    body_verbs: tuple[str, ...] = (),
    body_terms: tuple[str, ...] = (),
    cover_terms: tuple[str, ...] = (),
    name: str = "derived_body",
) -> LexicalEvidencePack:
    """Derive a generic lexical pack from legacy body vocabulary fields.

    Multi-word n-grams become the phrase tier (value 3, one distinct hit);
    single-word n-grams and body terms become the strong unigram tier
    (value 2, two distinct hits); verbs become the weak unigram tier
    (value 1, two distinct hits). Cover terms become exclusions.
    """
    phrases = tuple(
        dict.fromkeys(term for term in body_ngrams if len(term.split()) > 1)
    )
    single_ngrams = tuple(
        dict.fromkeys(term for term in body_ngrams if len(term.split()) == 1)
    )
    strong = tuple(dict.fromkeys((*single_ngrams, *body_terms)))
    weak = tuple(dict.fromkeys(body_verbs))

    tiers: list[EvidenceTier] = []
    if phrases:
        tiers.append(
            EvidenceTier(
                name="body_phrase",
                priority=30,
                value=3,
                terms=phrases,
                match_kind="ngram",
                min_distinct_hits=1,
            )
        )
    if strong:
        tiers.append(
            EvidenceTier(
                name="body_strong",
                priority=20,
                value=2,
                terms=strong,
                match_kind="unigram",
                min_distinct_hits=2,
            )
        )
    if weak:
        tiers.append(
            EvidenceTier(
                name="body_weak",
                priority=10,
                value=1,
                terms=weak,
                match_kind="unigram",
                min_distinct_hits=2,
            )
        )
    return LexicalEvidencePack(
        name=name,
        tiers=tuple(tiers),
        exclusion_terms=tuple(dict.fromkeys(cover_terms)),
    )


__all__ = [
    "BodyEvidencePack",
    "CoverEvidencePack",
    "derive_lexical_pack",
]
