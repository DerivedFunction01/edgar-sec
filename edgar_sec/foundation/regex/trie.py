"""Prefix tree (trie) compaction and factorization for long regex alternations."""

from __future__ import annotations

import re


class TrieNode:
    """Node in a character prefix trie."""

    __slots__ = ("children", "is_end")

    def __init__(self) -> None:
        self.children: dict[str, TrieNode] = {}
        self.is_end: bool = False

    def insert(self, word: str) -> None:
        node = self
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end = True


def build_prefix_trie(words: list[str]) -> TrieNode:
    """Build a prefix trie from a list of words or phrases."""
    root = TrieNode()
    for word in words:
        if word:
            root.insert(word)
    return root


def trie_to_regex(node: TrieNode, auto_escape: bool = True) -> str:
    """Convert a trie node into a minimal factored regex string.

    Factor common prefixes so a long alternation compiles to a compact regex.
    """
    if not node.children:
        return ""

    branches: list[str] = []
    for char, child in sorted(node.children.items()):
        escaped_char = re.escape(char) if auto_escape else char
        child_regex = trie_to_regex(child, auto_escape=auto_escape)
        if child_regex:
            branches.append(f"{escaped_char}{child_regex}")
        else:
            branches.append(escaped_char)

    if len(branches) == 1:
        result = branches[0]
    else:
        if all(len(b) == 1 or (len(b) == 2 and b.startswith("\\")) for b in branches):
            chars = "".join(b for b in branches)
            result = f"[{chars}]"
        else:
            result = f"(?:{'|'.join(branches)})"

    if node.is_end:
        return (
            f"(?:{result})?"
            if len(branches) > 1 or not result.startswith("(?:")
            else f"{result}?"
        )
    return result


def compact_alternation(words: list[str], auto_escape: bool = True) -> str:
    """Build a factored regex alternation from a list of words using a trie."""
    if not words:
        return ""
    if len(words) == 1:
        return re.escape(words[0]) if auto_escape else words[0]

    seen: set[str] = set()
    unique_words: list[str] = []
    for w in words:
        if w not in seen:
            unique_words.append(w)
            seen.add(w)

    trie = build_prefix_trie(unique_words)
    pattern = trie_to_regex(trie, auto_escape=auto_escape)

    if not (pattern.startswith("(?:") and pattern.endswith(")")):
        pattern = f"(?:{pattern})"
    return pattern


__all__ = [
    "TrieNode",
    "build_prefix_trie",
    "compact_alternation",
    "trie_to_regex",
]
