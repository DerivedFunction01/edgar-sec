"""Term index: one compiled matcher over a unified term census.

An index is built from (term, kind) entries; one traversal of a
text collects every kind at once. Word entries match on word
boundaries, phrase entries as literal substrings; overlaps report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class TermEntry:
    """One censused form: its kind, its match mode, its report value."""

    term: str
    kind: str
    word: bool = False
    value: str | None = None

    @property
    def reported(self) -> str:
        return self.term if self.value is None else self.value


def _is_word_char(char: str) -> bool:
    return char == "_" or char.isalnum()


class TermIndex:
    """Aho-Corasick automaton over the unified census of forms."""

    __slots__ = ("_children", "_fail", "_out")

    def __init__(self, entries: Iterable[TermEntry]) -> None:
        children: list[dict[str, int]] = [{}]
        out: list[list[tuple[TermEntry, int]]] = [[]]
        for entry in entries:
            if not entry.term:
                continue
            node = 0
            for char in entry.term:
                nxt = children[node].get(char)
                if nxt is None:
                    nxt = len(children)
                    children[node][char] = nxt
                    children.append({})
                    out.append([])
                node = nxt
            out[node].append((entry, len(entry.term)))
        fail = [0] * len(children)
        queue = list(children[0].values())
        for node in queue:
            fail[node] = 0
        index = 0
        while index < len(queue):
            node = queue[index]
            index += 1
            for char, nxt in children[node].items():
                queue.append(nxt)
                ancestor = fail[node]
                while ancestor and char not in children[ancestor]:
                    ancestor = fail[ancestor]
                fail[nxt] = children[ancestor].get(char, 0)
                out[nxt] = out[nxt] + out[fail[nxt]]
        self._children = children
        self._fail = fail
        self._out = out

    def scan(self, text: str) -> dict[str, frozenset[str]]:
        """One traversal: kind -> reported values found in the text."""
        found: dict[str, set[str]] = {}
        node = 0
        children, fail, out = self._children, self._fail, self._out
        for pos, char in enumerate(text):
            while node and char not in children[node]:
                node = fail[node]
            node = children[node].get(char, 0)
            for entry, length in out[node]:
                if entry.word:
                    start = pos - length + 1
                    if start > 0 and _is_word_char(text[start - 1]):
                        continue
                    if pos + 1 < len(text) and _is_word_char(text[pos + 1]):
                        continue
                found.setdefault(entry.kind, set()).add(entry.reported)
        return {kind: frozenset(values) for kind, values in found.items()}
