"""Term index: one traversal, both match semantics, overlaps."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex


def _index() -> TermIndex:
    return TermIndex(
        (
            TermEntry("cap", "base", word=True),
            TermEntry("caps", "base", word=True),
            TermEntry("swap", "base", word=True),
            TermEntry("derivative", "base", word=True),
            TermEntry("derivative assets", "designation"),
            TermEntry("fair value hedge", "designation"),
            TermEntry("own-use exemption", "npns"),
            TermEntry("capped", "stem", value="cap"),
            TermEntry("stock cap", "equity_prefixed", value="cap"),
            TermEntry("offsetting", "anchor"),
            TermEntry("offsetting", "offsetting"),
        )
    )


def test_word_terms_match_on_boundaries_only():
    index = _index()
    assert index.scan("the cap rate")["base"] == frozenset({"cap"})
    assert "base" not in index.scan("capacity and capped rates")
    assert index.scan("caps and cap")["base"] == frozenset({"cap", "caps"})


def test_phrase_terms_match_as_substrings():
    index = _index()
    hits = index.scan("fair value hedges are designated")
    assert hits["designation"] == frozenset({"fair value hedge"})
    assert index.scan("own-use exemption applies")["npns"] == frozenset(
        {"own-use exemption"}
    )


def test_overlaps_report_every_kind():
    index = _index()
    hits = index.scan("derivative assets and offsetting")
    assert hits["base"] == frozenset({"derivative"})
    assert hits["designation"] == frozenset({"derivative assets"})
    assert hits["anchor"] == frozenset({"offsetting"})
    assert hits["offsetting"] == frozenset({"offsetting"})


def test_reported_values_ride_entries():
    index = _index()
    hits = index.scan("capped rate and stock cap table")
    assert hits["stem"] == frozenset({"cap"})
    assert hits["equity_prefixed"] == frozenset({"cap"})


def test_empty_and_absent_texts_hit_nothing():
    index = _index()
    assert index.scan("") == {}
    assert index.scan("nothing censused here") == {}
