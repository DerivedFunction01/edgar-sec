"""Pins for the term-pattern home (Wave 2B).
The cached word-boundary compiler lives in
``derivatives_evidence``; ``geometry_scoring`` binds it.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade import geometry_scoring
from edgar_sec.engine.tables.extraction.evidence import derivatives_evidence


def test_binding_is_the_derivatives_home() -> None:
    assert geometry_scoring._term_pattern is derivatives_evidence._term_pattern


def test_term_pattern_verdicts() -> None:
    pattern = derivatives_evidence._term_pattern("note")
    assert pattern.search("see note 1") is not None
    assert pattern.search("notebook") is None
    assert pattern.search("denote") is None


def test_term_pattern_is_cached() -> None:
    assert derivatives_evidence._term_pattern("risk") is (
        derivatives_evidence._term_pattern("risk")
    )
