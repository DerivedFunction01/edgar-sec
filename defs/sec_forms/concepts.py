"""Semantic concept patterns supporting dual regex alternation and Bag-of-Words token matching."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from re import Match, Pattern

from defs.entities import NAME_STOPWORDS
from defs.regex import build_alternation


@dataclass(frozen=True, slots=True)
class ConceptPattern:
    """A statutory SEC concept supporting high-precision regex search and Bag-of-Words scoring."""

    name: str
    phrases: tuple[str, ...]
    regex: Pattern[str] = field(init=False)
    tokens: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        compiled = re.compile(rf"(?i)(?:{build_alternation(list(self.phrases))})")
        object.__setattr__(self, "regex", compiled)

        all_tokens: set[str] = set()
        for phrase in self.phrases:
            for word in re.findall(r"[a-z0-9]+", phrase.lower()):
                if len(word) > 1 and word not in NAME_STOPWORDS:
                    all_tokens.add(word)
        object.__setattr__(self, "tokens", frozenset(all_tokens))

    def search(self, text: str) -> Match[str] | None:
        """Search text using compiled alternation regex."""
        return self.regex.search(text)

    def finditer(self, text: str):
        """Iterate over regex matches in text."""
        return self.regex.finditer(text)

    def match_score(self, text: str) -> float:
        """Calculate Bag-of-Words token overlap score against text (0.0 to 1.0)."""
        words = set(re.findall(r"[a-z0-9]+", text.lower()))
        if not self.tokens:
            return 0.0
        return len(self.tokens.intersection(words)) / len(self.tokens)


__all__ = ["ConceptPattern"]
