"""Canonical English closed-class words, syntactic tokens, and prose grammar patterns.

This is a Level-1 Pure Data module: it depends only on standard library ``re``
and ``defs.regex``. It contains zero operational logic and never imports from
higher-level modules (tables, sec_forms, reflow). All consumers across the
repository compose these canonical definitions rather than maintaining local copies.
"""

from __future__ import annotations

import re

from defs.regex import build_alternation, compact_alternation

__all__ = [
    "ARTICLES",
    "FUNCTION_WORDS",
    "PROSE_TRANSITION_PHRASES",
    "RELATIVE_PRONOUNS",
    "RE_ARTICLE",
    "RE_POSSESSIVE",
    "RE_PROSE_TRANSITION_PHRASE",
    "RE_RELATIVE_PRONOUN",
    "RE_TRAILING_CONNECTOR",
    "RE_VERBAL_PARTICIPLE",
    "RE_WORD_TOKEN",
    "TRAILING_CONNECTORS",
]

# Canonical English articles
ARTICLES: tuple[str, ...] = ("the", "a", "an")
RE_ARTICLE: re.Pattern[str] = re.compile(
    rf"\b(?:{compact_alternation(ARTICLES)})\b",
    re.IGNORECASE,
)

# Relative and subordinating clause pronouns/adverbs
RELATIVE_PRONOUNS: tuple[str, ...] = ("which", "that", "whereby", "wherein")
RE_RELATIVE_PRONOUN: re.Pattern[str] = re.compile(
    rf"\b(?:{compact_alternation(RELATIVE_PRONOUNS)})\b",
    re.IGNORECASE,
)

# Standard English closed-class function/stop words (124 words)
FUNCTION_WORDS: frozenset[str] = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "may",
        "me",
        "might",
        "more",
        "most",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "year",
        "years",
        "ended",
        "respectively",
    ]
)

# Connectors and prepositions that indicate dangling line wraps when appearing at line ends
TRAILING_CONNECTORS: tuple[str, ...] = (
    "about",
    "after",
    "an",
    "and",
    "are",
    "as",
    "at",
    "before",
    "between",
    "but",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "that",
    "the",
    "through",
    "to",
    "under",
    "was",
    "were",
    "whereby",
    "wherein",
    "which",
    "with",
)
RE_TRAILING_CONNECTOR: re.Pattern[str] = re.compile(
    rf"\b(?:{build_alternation(TRAILING_CONNECTORS, auto_escape=True, sort_longest_first=True)})\s*$",
    re.IGNORECASE,
)

# High-frequency multi-word prose transition phrases
PROSE_TRANSITION_PHRASES: tuple[str, ...] = (
    "in connection with",
    "pursuant to",
    "as set forth",
    "in accordance with",
    "subject to",
    "with respect to",
    "as described in",
    "for the purpose of",
)
RE_PROSE_TRANSITION_PHRASE: re.Pattern[str] = re.compile(
    rf"\b(?:{build_alternation(PROSE_TRANSITION_PHRASES, auto_escape=True, sort_longest_first=True)})\b",
    re.IGNORECASE,
)

# Possessive enclitic ('s) attached to words
RE_POSSESSIVE: re.Pattern[str] = re.compile(r"\b[A-Za-z]{2,}'s\b")

# Verbal inflectional participles (-ing, -ed) with root >= 3 letters
RE_VERBAL_PARTICIPLE: re.Pattern[str] = re.compile(
    rf"\b[a-z]{{3,}}(?:{build_alternation(('ing', 'ed'), auto_escape=True)})\b",
    re.IGNORECASE,
)

# Word and numeric token pattern: alphanumeric words (with internal apostrophe),
# formatted numeric quantities (1,000.00, percentages), or single punctuation marks
RE_WORD_TOKEN: re.Pattern[str] = re.compile(
    r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:,\d{3})*(?:\.\d+)?%?|[^\w\s]"
)
