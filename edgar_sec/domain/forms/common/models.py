"""Typed evidence packs, profile models, and stage records for form families.

Defines pure data contracts consumed by form plugins and engine boundary detection.
``StageRecord`` joins them: it is the value the normalization chain writes at every
stage, so the engine produces it and pipelines serialize it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from edgar_sec.domain.forms.common.decisions import EvaluatorDecision
from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.foundation.text.evidence import EvidenceTier, LexicalEvidencePack
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


def _line_count(text: str) -> int:
    """Count ``\\n``-delimited lines without materializing a line list.

    Equivalent to ``len(text.splitlines())`` for text whose only separator is
    ``\\n`` and which carries no trailing newline, which is the shape the
    whitespace passes produce. Other Unicode separators are deliberately not
    counted: a form feed survives HTML projection, and this count is the one
    written into a stage record, so counting it here and not there would make
    two stages of the same document disagree about their own shape.
    """
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


@dataclass(frozen=True, slots=True)
class StageRecord:
    """One normalization stage's identity, proved by the text it emitted.

    A stage *name* cannot localize a divergence: two implementations can both
    report ``reflow`` and differ in the line the stage produced. The digest is
    therefore computed over the stage's own output, so the first record whose
    ``text_identity`` differs is the first stage that behaved differently. The
    counts are the cheap visual check that a divergence is a truncation or a
    reflow rather than a reordering.
    """

    stage: str
    text_identity: str
    line_count: int
    char_count: int

    @classmethod
    def of(cls, stage: str, text: str) -> StageRecord:
        """Record ``stage`` with the digest and counts of its output ``text``."""
        return cls(
            stage=stage,
            text_identity=sha256_text(text),
            line_count=_line_count(text),
            char_count=len(text),
        )

    def to_dict(self) -> dict[str, str | int]:
        """Return the JSON-shaped mapping a review artifact stores."""
        return dataclasses.asdict(self)


@dataclass(frozen=True, slots=True)
class ItemDefinition:
    """Canonical definition of a form structural item."""

    item: str
    part: int
    names: tuple[str, ...]
    optional: bool = False
    early: bool = False


def derive_lexical_pack(
    *,
    body_ngrams: tuple[str, ...] = (),
    body_verbs: tuple[str, ...] = (),
    body_terms: tuple[str, ...] = (),
    cover_terms: tuple[str, ...] = (),
    name: str = "derived_body",
) -> LexicalEvidencePack:
    """Derive a generic lexical pack from body vocabulary fields.

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
    "ContentTransform",
    "CoverEvidencePack",
    "Evaluator",
    "ItemDefinition",
    "StageRecord",
    "derive_lexical_pack",
]
