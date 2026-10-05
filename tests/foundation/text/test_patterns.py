"""Unit tests for edgar_sec.foundation.text.patterns."""

from __future__ import annotations

from edgar_sec.foundation.text.patterns import (
    RE_COLUMN_GAP,
    RE_DOT_LEADER,
    RE_PAGE_NUMBER_SUFFIX,
    RE_SENTENCE_TERMINAL,
    RE_SEPARATOR_LINE,
    RE_STRUCTURAL_SGML,
)


def test_dot_leader() -> None:
    assert RE_DOT_LEADER.search("Item 1. Business ...... 4") is not None
    assert RE_DOT_LEADER.search("Item 1. Business .. 4") is None


def test_column_gap() -> None:
    assert RE_COLUMN_GAP.search("Header 1    Header 2") is not None
    assert RE_COLUMN_GAP.search("Header 1 Header 2") is None


def test_page_number_suffix() -> None:
    assert RE_PAGE_NUMBER_SUFFIX.search("Table of Contents 42") is not None
    assert RE_PAGE_NUMBER_SUFFIX.search("Preface iv") is not None
    assert RE_PAGE_NUMBER_SUFFIX.search("Section 1A") is None


def test_sentence_terminal() -> None:
    assert RE_SENTENCE_TERMINAL.search("End of sentence.") is not None
    assert RE_SENTENCE_TERMINAL.search('End of sentence."') is not None
    assert RE_SENTENCE_TERMINAL.search("End of sentence!") is not None
    assert RE_SENTENCE_TERMINAL.search("Incomplete sentence") is None


def test_separator_line() -> None:
    assert RE_SEPARATOR_LINE.match("---") is not None
    assert RE_SEPARATOR_LINE.match("=== === ===") is not None
    assert RE_SEPARATOR_LINE.match("   ------   ") is not None
    assert RE_SEPARATOR_LINE.match("--- header ---") is None


def test_structural_sgml() -> None:
    assert RE_STRUCTURAL_SGML.search("<TABLE>") is not None
    assert RE_STRUCTURAL_SGML.search("<PAGE>") is not None
    assert RE_STRUCTURAL_SGML.search("<DOCUMENT>") is not None
    assert RE_STRUCTURAL_SGML.search("<div>") is None
