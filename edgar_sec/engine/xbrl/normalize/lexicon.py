"""Declarative token lexicon and longest-match phrase scanner."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class LexiconEntry:
    """A lexical entry binding a token phrase to its grammatical or semantic role."""

    phrase: tuple[str, ...]
    role: str
    atom: str | None = None
    mods: tuple[str, ...] = ()
    direction: float | None = None
    indexical: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LexiconEntry:
        """Construct a LexiconEntry from dictionary format."""
        raw_phrase = data.get("phrase", [])
        if isinstance(raw_phrase, str):
            phrase = tuple(p.lower() for p in raw_phrase.split())
        else:
            phrase = tuple(str(p).lower() for p in raw_phrase)
        raw_mods = data.get("mods", ())
        mods = (
            tuple(str(m) for m in raw_mods)
            if isinstance(raw_mods, (list, tuple))
            else ()
        )
        return cls(
            phrase=phrase,
            role=str(data.get("role", "")).upper(),
            atom=data.get("atom"),
            mods=mods,
            direction=float(data["direction"]) if "direction" in data else None,
            indexical=data.get("indexical"),
        )


@dataclass(frozen=True, slots=True)
class LexiconMatch:
    """A contiguous matched segment within a sequence of tokens."""

    start: int
    end: int
    entry: LexiconEntry


class TokenLexicon:
    """Declarative vocabulary managing phrase matching and grammatical roles."""

    def __init__(self, entries: tuple[LexiconEntry, ...]) -> None:
        """Initialize lexicon with entries indexed by phrase length."""
        self._entries = entries
        self._max_len = max((len(e.phrase) for e in entries), default=1)
        self._phrase_map: dict[tuple[str, ...], LexiconEntry] = {}
        for entry in sorted(entries, key=lambda e: len(e.phrase), reverse=True):
            if entry.phrase not in self._phrase_map:
                self._phrase_map[entry.phrase] = entry

    @property
    def entries(self) -> tuple[LexiconEntry, ...]:
        """All configured lexical entries."""
        return self._entries

    @classmethod
    def load_json(cls, path: Path | str) -> TokenLexicon:
        """Load TokenLexicon from a JSON file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        entries = tuple(LexiconEntry.from_dict(item) for item in data)
        return cls(entries)

    def scan_tokens(
        self, tokens: tuple[str, ...]
    ) -> tuple[list[LexiconMatch], list[str]]:
        """Greedily match longest phrases from left to right, returning matches and residuals."""
        lower_tokens = tuple(t.lower() for t in tokens)
        matches: list[LexiconMatch] = []
        residuals: list[str] = []
        i = 0
        n = len(lower_tokens)
        while i < n:
            matched = False
            for length in range(min(self._max_len, n - i), 0, -1):
                candidate = lower_tokens[i : i + length]
                if candidate in self._phrase_map:
                    entry = self._phrase_map[candidate]
                    matches.append(LexiconMatch(start=i, end=i + length, entry=entry))
                    i += length
                    matched = True
                    break
            if not matched:
                residuals.append(tokens[i])
                i += 1
        return matches, residuals
