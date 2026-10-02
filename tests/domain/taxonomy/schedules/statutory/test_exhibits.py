"""Tests for statutory exhibit index taxonomy and regex patterns."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.schedules.statutory.exhibits import (
    CANONICAL_EXHIBIT_HEADERS,
    EXHIBIT_INDEX_STATUTORY_PHRASES,
    RE_EXHIBIT_NUMBER,
    RE_EXHIBIT_STATUTORY_PHRASE,
)


def test_exhibit_index_phrases_populated() -> None:
    assert len(EXHIBIT_INDEX_STATUTORY_PHRASES) > 0
    assert "P1_exhibit_number" in EXHIBIT_INDEX_STATUTORY_PHRASES
    assert len(CANONICAL_EXHIBIT_HEADERS) > 0
    assert "Exhibit Number" in CANONICAL_EXHIBIT_HEADERS


def test_re_exhibit_number_matches() -> None:
    assert RE_EXHIBIT_NUMBER.search("Item 10.1 Material Contract")
    assert RE_EXHIBIT_NUMBER.search("Exhibit 4.2 Description of Capital Stock")
    assert RE_EXHIBIT_NUMBER.search("Exhibit 99.1")
    assert not RE_EXHIBIT_NUMBER.search("No exhibit here")


def test_re_exhibit_statutory_phrase_matches() -> None:
    assert RE_EXHIBIT_STATUTORY_PHRASE.search("Incorporated by reference to Form 10-K")
    assert RE_EXHIBIT_STATUTORY_PHRASE.search("Filed herewith")
    assert RE_EXHIBIT_STATUTORY_PHRASE.search("Commission file number 001-12345")
    assert not RE_EXHIBIT_STATUTORY_PHRASE.search("Random text with no statutory cue")
