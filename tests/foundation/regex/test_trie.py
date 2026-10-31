"""Unit tests for TrieNode, build_prefix_trie, trie_to_regex, and compact_alternation."""

import re

from edgar_sec.foundation.regex.trie import (
    TrieNode,
    compact_alternation,
)


def test_trie_insert_and_structure() -> None:
    trie = TrieNode()
    trie.insert("cat")
    trie.insert("car")
    trie.insert("cart")

    assert "c" in trie.children
    assert "a" in trie.children["c"].children
    assert "t" in trie.children["c"].children["a"].children
    assert "r" in trie.children["c"].children["a"].children
    assert trie.children["c"].children["a"].children["t"].is_end
    assert trie.children["c"].children["a"].children["r"].is_end
    assert trie.children["c"].children["a"].children["r"].children["t"].is_end


def test_trie_empty_and_single() -> None:
    assert compact_alternation([]) == ""
    assert compact_alternation(["hello"]) == "hello"
    assert compact_alternation(["hello*"], auto_escape=True) == r"hello\*"


def test_compact_alternation_factoring() -> None:
    words = ["swap", "swap agreement", "swap option"]
    factored = compact_alternation(words)
    pattern = re.compile(factored)

    for word in words:
        assert pattern.fullmatch(word) is not None

    assert pattern.fullmatch("swapper") is None


def test_compact_alternation_deduplication() -> None:
    words = ["bond", "bond", "equity", "bond"]
    pattern_str = compact_alternation(words)
    pattern = re.compile(pattern_str)

    assert pattern.fullmatch("bond") is not None
    assert pattern.fullmatch("equity") is not None
