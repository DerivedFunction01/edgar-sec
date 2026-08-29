"""Shared regex construction, prefix trie factorization, and formatting tools."""

from __future__ import annotations

from .builder import (
    add_restrictions,
    build_alternation,
    build_compound,
    build_regex,
    plural,
    to_build_alternation,
    to_list,
)
from .formatting import to_verbose_pattern
from .trie import TrieNode, build_prefix_trie, compact_alternation, trie_to_regex

__all__ = [
    "TrieNode",
    "add_restrictions",
    "build_alternation",
    "build_compound",
    "build_prefix_trie",
    "build_regex",
    "compact_alternation",
    "plural",
    "to_build_alternation",
    "to_list",
    "to_verbose_pattern",
    "trie_to_regex",
]
