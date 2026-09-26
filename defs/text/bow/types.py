"""Shared low-level types for the lexical evidence matcher."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CaseMode(StrEnum):
    """How a configured term is compared against source text tokens."""

    FOLD = "fold"
    EXACT = "exact"
    LOWERCASE = "lowercase"


@dataclass(frozen=True, slots=True)
class Token:
    """One source-text token with both surface and folded views."""

    surface: str
    folded: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class CompiledTier:
    """A tier with normalized, length-grouped token indexes."""

    name: str
    priority: int
    value: int
    match_kind: str
    min_distinct_hits: int
    case_mode: CaseMode
    support: bool = False
    unigrams: frozenset[str] = frozenset()
    ngram_index: dict[int, frozenset[tuple[str, ...]]] | None = None


@dataclass(frozen=True, slots=True)
class CompiledEvidencePack:
    """A pack compiled once for reuse across many units."""

    name: str
    tiers: tuple[CompiledTier, ...]
    band_max_value: tuple[int, ...]
    exclusions: frozenset[str] = frozenset()
    automaton: object | None = None


def token_to_key(token: Token, mode: CaseMode) -> str | None:
    """Return the lookup key for a token under a case mode, or None to skip."""
    if mode is CaseMode.FOLD:
        return token.folded
    if mode is CaseMode.EXACT:
        return token.surface
    if mode is CaseMode.LOWERCASE:
        return token.surface if token.surface.islower() else None
    raise ValueError(f"unsupported case mode: {mode!r}")


def window_key(
    tokens: list[Token], start: int, length: int, mode: CaseMode
) -> str | None:
    """Build the lookup key for an n-gram window, or return None to skip."""
    keys: list[str] = []
    for index in range(length):
        key = token_to_key(tokens[start + index], mode)
        if key is None:
            return None
        keys.append(key)
    return " ".join(keys)


__all__ = [
    "CaseMode",
    "CompiledEvidencePack",
    "CompiledTier",
    "Token",
    "token_to_key",
    "window_key",
]
