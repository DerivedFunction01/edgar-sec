"""Shared prose evidence for page-marker discovery."""

from __future__ import annotations

from defs.text.automaton import compile_lexical_matcher

from .constants import PROSE_GUARD_STOP_WORDS

_PROSE_WORDS = frozenset(
    {
        *PROSE_GUARD_STOP_WORDS,
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)
_MATCHER = compile_lexical_matcher({"page_marker_prose": sorted(_PROSE_WORDS)})


def prose_stop_words(text: str) -> frozenset[str]:
    """Return distinct grammar words found in a candidate text."""
    return frozenset(match.term.casefold() for match in _MATCHER.find_matches(text))


def looks_like_prose(text: str, *, minimum_hits: int = 3) -> bool:
    """Classify a longer candidate as prose using shared lexical evidence."""
    words = text.split()
    return len(words) >= 6 and len(prose_stop_words(text)) >= minimum_hits


__all__ = ["looks_like_prose", "prose_stop_words"]
