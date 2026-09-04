"""Stop word sets and token categories for the table probe."""

from __future__ import annotations

GRAMMAR_STOP_WORDS = frozenset(
    [
        "the",
        "and",
        "of",
        "to",
        "in",
        "for",
        "as",
        "a",
        "an",
        "by",
        "from",
        "or",
        "on",
        "with",
        "at",
        "under",
        "over",
        "its",
        "their",
        "this",
        "that",
        "is",
        "are",
        "be",
        "was",
        "were",
        "s",
        "u",
        "#",
    ]
)

CORPORATE_BOILERPLATE = frozenset(
    [
        "we",
        "our",
        "us",
        "company",
        "registrant",
        "inc",
        "corp",
        "corporation",
        "llc",
        "consolidated",
        "certain",
        "see",
        "note",
        "notes",
        "included",
        "applicable",
        "respectively",
        "approximate",
        "approximately",
    ]
)

UNIT_TOKENS = frozenset(
    [
        "millions",
        "thousands",
        "dollars",
        "share",
        "shares",
        "percent",
        "basis",
        "points",
        "ratio",
        "ratios",
        "units",
        "per",
    ]
)

STOP_WORDS = frozenset(GRAMMAR_STOP_WORDS | CORPORATE_BOILERPLATE)

__all__ = [
    "CORPORATE_BOILERPLATE",
    "GRAMMAR_STOP_WORDS",
    "STOP_WORDS",
    "UNIT_TOKENS",
]
