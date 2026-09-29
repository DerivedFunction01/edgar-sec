"""Lexical body-prose scoring for cover/body boundary detection.

Scores a candidate text unit as body prose on a 0-3 scale, where 2 is the gate
the boundary detectors accept. The score comes from a single Aho-Corasick pass
over the generic evidence vocabulary in
:mod:`edgar_sec.domain.forms.body_evidence`.

Departure from v1
-----------------
v1 ran a tiered bag-of-words engine (``defs/text/bow``) with per-tier weights,
minimum-distinct-hit thresholds, and per-form packs. v2's
``foundation.text.automaton`` compiles a single tier per category, so this
module collapses v1's four tiers into one distinct-hit count calibrated to the
same 0-3 scale:

===========  ==================================================
distinct     interpretation
hits
===========  ==================================================
0-1          weak / ambiguous, below every acceptance gate
2            accepted: body prose
3+           decisive: body prose with high confidence
===========  ==================================================

Cover-exclusion terms veto a unit outright, matching v1's exclusion tier: a
paragraph carrying a cover-only label is never body prose regardless of how
much narrative vocabulary it also contains.
"""

from __future__ import annotations

from edgar_sec.domain.forms.body_evidence import (
    BODY_FORWARD_TERMS,
    BODY_SEMANTIC_HEADINGS,
    BODY_SOFT_PHRASES,
    BODY_STRONG_PHRASES,
    BODY_STRONG_TERMS,
    BODY_WEAK_TERMS,
    COVER_EXCLUSION_TERMS,
)
from edgar_sec.foundation.text.automaton import (
    LexicalMatcher,
    compile_lexical_matcher,
    tier_confidence,
)

BODY_CATEGORY = "body_prose"

#: Score at or above which a unit is accepted as body prose.
MIN_BODY_SCORE = 2

#: Confidence contributed per distinct-hit count, mirroring v1's ladder.
_SCORE_CONFIDENCE = {0: 0.0, 1: 0.5, 2: 0.7, 3: 0.85}


def _distinct_hits(matches: tuple, tier_terms: frozenset[str]) -> int:
    return len(
        {
            match.term.casefold()
            for match in matches
            if match.term.casefold() in tier_terms
        }
    )


def build_body_matcher() -> LexicalMatcher:
    """Compile the body-prose matcher over the generic evidence vocabulary."""
    categories = {
        BODY_CATEGORY: (
            *BODY_STRONG_PHRASES,
            *BODY_SOFT_PHRASES,
            *BODY_STRONG_TERMS,
            *BODY_WEAK_TERMS,
            *BODY_FORWARD_TERMS,
        )
    }
    exclusions = {BODY_CATEGORY: COVER_EXCLUSION_TERMS}
    return compile_lexical_matcher(categories, exclusions)


_STRONG_PHRASES_FOLDED = frozenset(p.casefold() for p in BODY_STRONG_PHRASES)
_SOFT_PHRASES_FOLDED = frozenset(p.casefold() for p in BODY_SOFT_PHRASES)
_STRONG_TERMS_FOLDED = frozenset(t.casefold() for t in BODY_STRONG_TERMS)
_WEAK_TERMS_FOLDED = frozenset(t.casefold() for t in BODY_WEAK_TERMS)
_FORWARD_TERMS_FOLDED = frozenset(t.casefold() for t in BODY_FORWARD_TERMS)
_SEMANTIC_HEADINGS_FOLDED = frozenset(h.casefold() for h in BODY_SEMANTIC_HEADINGS)

_MATCHER = build_body_matcher()


def score_body_text(text: str) -> int:
    """Score one text unit as body prose on the 0-3 scale.

    A decisive strong phrase scores 3 regardless of breadth, mirroring v1's
    "one distinct phrase hit confirms body prose" rule. Otherwise the score is
    the distinct-hit count across the term tiers, capped at 3.
    """
    if not text:
        return 0
    matches = _MATCHER.find_matches(text)
    if any(match.is_exclusion for match in matches):
        return 0
    if not matches:
        return 0

    body_matches = tuple(m for m in matches if not m.is_exclusion)
    if _distinct_hits(body_matches, _STRONG_PHRASES_FOLDED) >= 1:
        return 3
    if _distinct_hits(body_matches, _SOFT_PHRASES_FOLDED) >= 2:
        return 2

    term_hits = (
        _distinct_hits(body_matches, _STRONG_TERMS_FOLDED)
        + _distinct_hits(body_matches, _WEAK_TERMS_FOLDED)
        + _distinct_hits(body_matches, _FORWARD_TERMS_FOLDED)
    )
    if _distinct_hits(body_matches, _STRONG_TERMS_FOLDED) >= 2:
        return 3
    return min(3, term_hits)


def score_confidence(score: int) -> float:
    """Return the calibrated confidence for a body-prose score."""
    return _SCORE_CONFIDENCE.get(score, 0.0)


def tier_confidence_for(score: int) -> float:
    """Return confidence using the shared automaton calibration."""
    if score <= 0:
        return 0.0
    return tier_confidence(score, score)


def is_body_prose(text: str) -> bool:
    """Return whether ``text`` clears the body-prose acceptance gate."""
    return score_body_text(text) >= MIN_BODY_SCORE


def is_semantic_heading(text: str) -> bool:
    """Return whether ``text`` names a substantive discussion section."""
    if not text:
        return False
    lowered = text.casefold()
    return any(heading in lowered for heading in _SEMANTIC_HEADINGS_FOLDED)


def describe_score(score: int) -> str:
    """Render a score for the evidence trace."""
    return f"body score {score}"


__all__ = [
    "BODY_CATEGORY",
    "MIN_BODY_SCORE",
    "build_body_matcher",
    "describe_score",
    "is_body_prose",
    "is_semantic_heading",
    "score_body_text",
    "score_confidence",
    "tier_confidence_for",
]
