"""Token normalization for universe-scale family assignment.

One pass per registrant produces an ordered token list; every downstream decision is a
SQL relation over those tokens. Reuses the engine's trademark and jurisdiction rules
rather than a second copy of them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from edgar_sec.domain.taxonomy.family_vocab import (
    ABBR_MAP,
    CONTEXT_RULES,
    CORPORATE_DESIGNATORS,
    INSTITUTION_ALIASES,
    ORDINAL_WORDS,
    PLURAL_MAP,
    SPV_MARKERS,
    SPONSOR_BOUNDARY_WORDS,
    strippable_postal_codes,
)
from edgar_sec.domain.taxonomy.jurisdictions import strip_jurisdiction
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.tokens import roman_to_int

# Separators that carry no identity, including the typographic quotes EDGAR carries.
PUNCT_RE = re.compile(r"[^a-z0-9]+")

TRADEMARK_MARKERS = ("sm", "tm", "r", "c")
TRADEMARK_RE = re.compile(
    rf"\({build_alternation(sorted(TRADEMARK_MARKERS), auto_escape=True)}\)",
    re.IGNORECASE,
)

# Function words dropped before comparison. The umbrella phrase is read from the raw
# name, so dropping these here costs nothing.
DROP_TOKENS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "or",
        "and",
        "as",
        "is",
        "for",
        "by",
        "in",
        "on",
        "at",
        "to",
    }
)

_STRIP_POSTAL = strippable_postal_codes()
_UMBRELLA = "a series of"


def is_identifier(token: str) -> bool:
    """Report a series or vintage marker: digit, initial, Roman numeral, or code.

    Roman numerals are parsed rather than looked up, so `series xxxi` folds like the
    rest instead of resisting a fixed table.
    """
    if token.isdigit():
        return True
    if len(token) == 1:
        return token.isalpha()
    if any(char.isdigit() for char in token) and any(char.isalpha() for char in token):
        return True
    return roman_to_int(token) is not None


def _expand(tokens: Sequence[str]) -> list[str]:
    """Apply the abbreviation tables, then the context-sensitive ones.

    Context rules run over the already-expanded sequence so a rule may read a
    neighbour that abbreviation expansion just produced.
    """
    expanded: list[str] = []
    for token in tokens:
        expansion = ABBR_MAP.get(token)
        expanded.extend(expansion.split() if expansion else [token])

    refined: list[str] = []
    last = len(expanded) - 1
    for position, token in enumerate(expanded):
        rule = CONTEXT_RULES.get(token)
        if rule is None:
            refined.append(token)
            continue
        expansion, allowed_prev, allowed_next = rule
        previous = expanded[position - 1] if position > 0 else ""
        following = expanded[position + 1] if position < last else ""
        if (not allowed_prev or previous in allowed_prev) and (
            not allowed_next or following in allowed_next
        ):
            refined.append(expansion)
        else:
            refined.append(token)
    return refined


def normalize_tokens(name: str) -> list[str]:
    """Return the ordered tokens of one registrant name, identifiers still in place.

    Identifiers are kept because their position is what marks a deal boundary; the
    identity stem drops them separately.
    """
    if not name:
        return []
    text = strip_jurisdiction(name)
    text = TRADEMARK_RE.sub(" ", text).lower()
    tokens = [t for t in PUNCT_RE.split(text) if t]

    tokens = _expand(tokens)
    folded = [PLURAL_MAP.get(t, ORDINAL_WORDS.get(t, t)) for t in tokens]
    return [
        t
        for position, t in enumerate(folded)
        if t not in _STRIP_POSTAL and (t not in DROP_TOKENS or position == 0)
    ]


def identity_tokens(name: str) -> list[str]:
    """Return the identity-bearing stem: identifiers dropped, designator tails peeled.

    Peeling alternates, because a legal form can sit on either side of a deal marker, and
    stops before the stem is only a legal form.
    """
    kept = [t for t in normalize_tokens(name) if not is_identifier(t)]
    while kept and all(t in CORPORATE_DESIGNATORS for t in kept):
        return []
    while len(kept) > 1 and kept[-1] in CORPORATE_DESIGNATORS:
        kept.pop()
    return kept


def apply_aliases(stem: str) -> str:
    """Fold a reviewed institution spelling onto its canonical form.

    Applied before the SPV test, because a token split alone must not change namespace.
    """
    if not stem:
        return stem
    canonical = INSTITUTION_ALIASES.get(stem.replace(" ", ""))
    return canonical if canonical else stem


def normalized_key(name: str) -> str:
    """Space-joined identity stem with aliases applied, which is the stored key text."""
    return apply_aliases(" ".join(identity_tokens(name)))


def has_spv_marker(name: str) -> bool:
    """Report whether a name describes a securitised vehicle rather than an entity.

    Read from the alias-folded identity stem, so a reviewed spelling cannot be moved
    between namespaces by token splitting alone.
    """
    stem = normalized_key(name)
    return bool(stem) and any(token in SPV_MARKERS for token in stem.split(" "))


def sponsor_candidate(name: str) -> str:
    """Return the tokens before the first boundary word, as a fallback sponsor.

    Only used when no known entity prefix matches; a one-token result is ambiguous
    and the caller must fail closed rather than merge it across sponsors.
    """
    stem = apply_aliases(" ".join(identity_tokens(name)))
    tokens = [t for t in stem.split(" ") if t]
    for position, token in enumerate(tokens):
        if token in SPONSOR_BOUNDARY_WORDS:
            return " ".join(tokens[:position])
    return " ".join(tokens)


def contains_umbrella(name: str) -> bool:
    """Report the phrase that names a parent outright, e.g. `A SERIES OF <parent>`."""
    if not name:
        return False
    return _UMBRELLA in PUNCT_RE.sub(" ", name.lower())


def umbrella_parent(name: str) -> str:
    """Return the normalized parent named after `A SERIES OF`, or empty.

    Taken verbatim, because the right-hand side beats any prefix match. Identifiers are
    kept here though they never reach a stem: `CGF2021` is a parent that looks like a code.
    """
    if not name:
        return ""
    text = PUNCT_RE.sub(" ", name.lower())
    position = text.find(_UMBRELLA)
    if position < 0:
        return ""
    kept = list(normalize_tokens(text[position + len(_UMBRELLA) :]))
    while len(kept) > 1 and kept[-1] in CORPORATE_DESIGNATORS:
        if not any(t not in CORPORATE_DESIGNATORS for t in kept[:-1]):
            break
        kept.pop()
    return apply_aliases(" ".join(kept))


__all__ = [
    "DROP_TOKENS",
    "apply_aliases",
    "PUNCT_RE",
    "TRADEMARK_RE",
    "contains_umbrella",
    "has_spv_marker",
    "identity_tokens",
    "is_identifier",
    "normalize_tokens",
    "normalized_key",
    "sponsor_candidate",
    "umbrella_parent",
]
