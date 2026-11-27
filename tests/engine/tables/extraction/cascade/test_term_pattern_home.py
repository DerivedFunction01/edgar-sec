"""Pins for the term-matcher home.
The shared single-pass matcher lives in ``core.term_index``;
``geometry_scoring`` binds its ``term_present``.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry import geometry_scoring
from edgar_sec.engine.tables.extraction.core import term_index


def test_binding_is_the_term_index_home() -> None:
    assert geometry_scoring.term_present is term_index.term_present


def test_term_present_verdicts() -> None:
    assert term_index.term_present("note", "see note 1")
    assert not term_index.term_present("note", "notebook")
    assert not term_index.term_present("note", "denote")


def test_single_term_index_is_cached() -> None:
    assert term_index._single("risk") is term_index._single("risk")
