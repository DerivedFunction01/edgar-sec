"""Internal matching primitives for the shared lexical evidence engine.

This module is an implementation detail of ``defs.text.bow``. It owns the
per-tier matchers, the band maximum helper, and the reason builder that
the public scorer dispatches. Form-specific and domain vocabulary never
appears here.
"""

from __future__ import annotations

from defs.text.bow_types import CompiledTier, Token, token_to_key, window_key


def match_unigrams(
    tokens: list[Token], vocab: frozenset[str], mode: object
) -> dict[str, list[int]]:
    """Return matched unigram terms and their source positions."""
    matched: dict[str, list[int]] = {}
    for position, token in enumerate(tokens):
        key = token_to_key(token, mode)
        if key is None or key not in vocab:
            continue
        matched.setdefault(key, []).append(position)
    return matched


def match_ngrams(
    tokens: list[Token],
    index_by_length: dict[int, frozenset[tuple[str, ...]]],
    mode: object,
) -> dict[tuple[str, ...], list[int]]:
    """Return matched n-gram phrases and their start positions."""
    matched: dict[tuple[str, ...], list[int]] = {}
    token_count = len(tokens)
    for length, index in index_by_length.items():
        if length > token_count:
            continue
        for start in range(token_count - length + 1):
            key = window_key(tokens, start, length, mode)
            if key is None:
                continue
            phrase = tuple(key.split(" "))
            if phrase in index:
                matched.setdefault(phrase, []).append(start)
    return matched


def band_max_values(compiled: list[CompiledTier]) -> tuple[int, ...]:
    """Return the maximum value per priority band, in priority-descending order.

    Same-priority tiers share a band; the band max is the max of its
    members. Useful as a trace signal and for upper-bound reasoning.
    """
    if not compiled:
        return ()
    bands: list[int] = []
    current_priority: int | None = None
    current_max = 0
    for tier in compiled:
        if tier.priority != current_priority:
            if current_priority is not None:
                bands.append(current_max)
            current_priority = tier.priority
            current_max = tier.value
        else:
            current_max = max(current_max, tier.value)
    if current_priority is not None:
        bands.append(current_max)
    return tuple(bands)


def tier_confidence(value: int, distinct_hits: int) -> float:
    """Calibrated confidence for a satisfied tier."""
    if value >= 3:
        return min(0.98, 0.9 + 0.02 * distinct_hits)
    if value >= 2:
        return min(0.95, 0.8 + 0.03 * distinct_hits)
    return min(0.6, 0.45 + 0.05 * distinct_hits)


def build_reason(
    score: int,
    satisfied: list[str],
    partial_strong: bool,
    exclusions: tuple[str, ...],
    pack_name: str,
) -> str:
    if score >= 2:
        return f"satisfied tier(s) {satisfied} with decisive evidence"
    if score == 1 and satisfied:
        return f"satisfied weak tier(s) {satisfied}"
    if score == 1:
        return "partial high-confidence evidence below distinct-hit minimum"
    if exclusions:
        preview = ", ".join(exclusions[:5])
        return f"form/cover exclusion terms only: {preview}"
    return f"no lexical evidence matched in pack {pack_name!r}"


__all__ = [
    "band_max_values",
    "build_reason",
    "match_ngrams",
    "match_unigrams",
    "tier_confidence",
]
