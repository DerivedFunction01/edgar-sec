"""Deterministic name normalization for company-family resolution: strip markers,
tokenize, expand abbreviations, fold plurals, then collapse digits, single letters,
and roman numerals to placeholders. Every step is pure.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from edgar_sec.domain.taxonomy.family_vocab import (
    ABBR_MAP,
    CONTEXT_RULES,
    HEAD_TOKENS,
    MAX_PARENT_TOKENS,
    PLACEHOLDER,
    PLURAL_MAP,
    ROMAN,
    STRUCTURAL_THRESHOLD,
)
from edgar_sec.domain.taxonomy.jurisdictions import JURISDICTION_RE
from edgar_sec.domain.taxonomy.legal_forms import LEGAL_FORMS
from edgar_sec.foundation.regex.builder import build_alternation

# Separators that carry no identity. Includes the em dash and typographic quotes
# that appear in EDGAR names.
PUNCT_RE = re.compile(r"[/\\,._\-—()\[\]{}'\"’`&]+")

# Bare parenthesised trademark markers: (R), (TM), (SM), (C).
TRADEMARK_RE = re.compile(
    rf"\({build_alternation(['sm', 'tm', 'r', 'c'])}\)",
    re.IGNORECASE,
)

DIGIT_PLACEHOLDER = "D"
SINGLE_LETTER_PLACEHOLDER = "S"
ROMAN_PLACEHOLDER = "R"


def normalize_name(name: str) -> list[str]:
    """Tokenize a raw company name and expand its abbreviations."""
    if not name:
        return []
    text = name.strip()
    text = JURISDICTION_RE.sub(" ", text)
    text = TRADEMARK_RE.sub(" ", text)
    text = PUNCT_RE.sub(" ", text).lower()

    raw_tokens = text.split()
    if not raw_tokens:
        return []

    tokens: list[str] = []
    for token in raw_tokens:
        expansion = ABBR_MAP.get(token)
        if expansion is not None:
            tokens.extend(expansion.split())
        else:
            tokens.append(token)

    # Context-sensitive expansion runs over the *expanded* sequence, so a rule
    # may look at neighbours that abbreviation expansion just produced.
    refined: list[str] = []
    count = len(tokens)
    for position, token in enumerate(tokens):
        rule = CONTEXT_RULES.get(token)
        if rule is None:
            refined.append(token)
            continue
        expansion, allowed_prev, allowed_next = rule
        previous = tokens[position - 1] if position > 0 else ""
        following = tokens[position + 1] if position + 1 < count else ""
        prev_ok = not allowed_prev or previous in allowed_prev
        next_ok = not allowed_next or following in allowed_next
        refined.append(expansion if prev_ok and next_ok else token)

    return [PLURAL_MAP.get(token, token) for token in refined]


def post_normalize(tokens: Sequence[str]) -> list[str]:
    """Collapse digits, single letters, and roman numerals to placeholders; a series
    number is not identity, so "2011-C5" and "2007-2" are one trust.
    """
    output: list[str] = []
    for token in tokens:
        if token.isdigit():
            output.append(DIGIT_PLACEHOLDER)
        elif len(token) == 1 and token.isalpha():
            output.append(SINGLE_LETTER_PLACEHOLDER)
        elif token.lower() in ROMAN:
            output.append(ROMAN_PLACEHOLDER)
        else:
            output.append(token)
    return output


def strip_legal_forms(tokens: Sequence[str]) -> list[str]:
    """Remove legal and entity-type suffixes from a token sequence."""
    return [token for token in tokens if token not in LEGAL_FORMS]


def normalized_body(name: str) -> list[str]:
    """Run the full normalization chain and return the comparable token body."""
    return strip_legal_forms(post_normalize(normalize_name(name)))


def first_structural_index(
    body: Sequence[str], structural_vocab: frozenset[str]
) -> int:
    """Index of the first structural token, or `len(body)`: everything before it is
    the distinguishing key, from it onward shared series vocabulary.
    """
    for position, token in enumerate(body):
        if token in structural_vocab or token == DIGIT_PLACEHOLDER:
            return position
    return len(body)


def count_structural_tokens(
    body: Sequence[str], structural_vocab: frozenset[str]
) -> int:
    """Return how many structural tokens the body carries."""
    return sum(
        1 for token in body if token in structural_vocab or token == DIGIT_PLACEHOLDER
    )


def clean_key(body: Sequence[str], structural_vocab: frozenset[str]) -> tuple[str, ...]:
    """Return the family key for a body, excluding placeholder tokens."""
    boundary = first_structural_index(body, structural_vocab)
    return tuple(token for token in body[:boundary] if token not in PLACEHOLDER)


def is_variant(body: Sequence[str], structural_vocab: frozenset[str]) -> bool:
    """Report whether a name is a series variant rather than a parent."""
    if not body:
        return False
    structural = count_structural_tokens(body, structural_vocab)
    if structural == 0:
        return False
    return structural > STRUCTURAL_THRESHOLD


def is_plausible_parent(body: Sequence[str]) -> bool:
    """Report whether a body is short enough to be the family's parent name."""
    return len(body) <= MAX_PARENT_TOKENS


def mine_structural_vocabulary(
    names: Sequence[str],
    *,
    min_name_len: int = 6,
    head_tokens: int = HEAD_TOKENS,
    min_tail_freq: int | None = None,
    max_prefix_share: float = 0.35,
) -> frozenset[str]:
    """Mine the shared structural tail vocabulary: structural means frequent in a
    name's tail and rare in its head. Thresholds relax for small corpora.
    """
    large_corpus = len(names) >= 100
    effective_min_tail = (
        min_tail_freq if min_tail_freq is not None else (8 if large_corpus else 1)
    )
    min_len = min_name_len if large_corpus else 3

    long_names: list[list[str]] = []
    for name in names:
        body = normalized_body(name)
        if len(body) >= min_len:
            long_names.append(body)

    prefix_counts: Counter[str] = Counter()
    tail_counts: Counter[str] = Counter()
    for body in long_names:
        for token in body[:head_tokens]:
            if token not in PLACEHOLDER:
                prefix_counts[token] += 1
        for token in body[head_tokens:]:
            if token not in PLACEHOLDER:
                tail_counts[token] += 1

    structural: set[str] = set()
    for token, tail_count in tail_counts.items():
        if tail_count < effective_min_tail:
            continue
        prefix_count = prefix_counts.get(token, 0)
        share = prefix_count / (prefix_count + tail_count)
        if share < max_prefix_share:
            structural.add(token)

    return frozenset(structural - LEGAL_FORMS)


__all__ = [
    "DIGIT_PLACEHOLDER",
    "PUNCT_RE",
    "ROMAN_PLACEHOLDER",
    "SINGLE_LETTER_PLACEHOLDER",
    "TRADEMARK_RE",
    "clean_key",
    "count_structural_tokens",
    "first_structural_index",
    "is_plausible_parent",
    "is_variant",
    "mine_structural_vocabulary",
    "normalize_name",
    "normalized_body",
    "post_normalize",
    "strip_legal_forms",
]
