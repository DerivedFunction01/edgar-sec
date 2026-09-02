"""Contract and unit tests for shared page-marker analysis."""

from __future__ import annotations

import importlib

import pytest

pm_mod = importlib.import_module("defs.sec_forms.page_markers")

PageMarker = pm_mod.PageMarker
PageMarkerAction = pm_mod.PageMarkerAction
PageMarkerAnalysis = pm_mod.PageMarkerAnalysis
PageMarkerDecision = pm_mod.PageMarkerDecision
PageMarkerKind = pm_mod.PageMarkerKind
PageMarkerSpan = pm_mod.PageMarkerSpan
analyze_page_markers = pm_mod.analyze_page_markers
find_page_markers = pm_mod.find_page_markers
strip_page_markers = pm_mod.strip_page_markers


def test_page_marker_sgml_standalone_line() -> None:
    text = "<PAGE>\nITEM 1. BUSINESS\n</PAGE>\n"
    analysis = analyze_page_markers(text)
    assert len(analysis.markers) == 2
    assert analysis.markers[0].kind == PageMarkerKind.SGML
    assert analysis.markers[1].kind == PageMarkerKind.SGML
    assert all(d.action == PageMarkerAction.REMOVE for d in analysis.decisions)


def test_page_marker_sgml_with_page_number() -> None:
    text = "<PAGE> 12\nITEM 1. BUSINESS\n"
    analysis = analyze_page_markers(text)
    assert len(analysis.markers) == 1
    marker = analysis.markers[0]
    assert marker.kind == PageMarkerKind.SGML
    assert marker.page_number == 12
    assert analysis.decisions[0].action == PageMarkerAction.REMOVE


def test_page_marker_dashed_numbers() -> None:
    text = "-1-\nSome text\n-  42  -\n"
    analysis = analyze_page_markers(text)
    assert len(analysis.markers) == 2
    assert analysis.markers[0].kind == PageMarkerKind.DASHED_NUMBER
    assert analysis.markers[0].page_number == 1
    assert analysis.markers[1].kind == PageMarkerKind.DASHED_NUMBER
    assert analysis.markers[1].page_number == 42
    assert all(d.action == PageMarkerAction.REMOVE for d in analysis.decisions)


def test_page_marker_page_number_alone() -> None:
    text = "Page 5\nSome text\npage 6\n"
    analysis = analyze_page_markers(text)
    assert len(analysis.markers) == 2
    assert analysis.markers[0].kind == PageMarkerKind.PAGE_NUMBER
    assert analysis.markers[0].page_number == 5
    assert analysis.markers[1].kind == PageMarkerKind.PAGE_NUMBER
    assert analysis.markers[1].page_number == 6


def test_page_marker_number_of_total() -> None:
    text = "1 of 125\nSome content\nPage 2 of 125\n"
    analysis = analyze_page_markers(text)
    assert len(analysis.markers) == 2
    assert analysis.markers[0].kind == PageMarkerKind.NUMBER_OF_TOTAL
    assert analysis.markers[0].page_number == 1
    assert analysis.markers[0].page_count == 125
    assert analysis.markers[1].kind == PageMarkerKind.PAGE_NUMBER_OF_TOTAL
    assert analysis.markers[1].page_number == 2
    assert analysis.markers[1].page_count == 125


def test_page_marker_inline_sgml() -> None:
    text = "Heading line <PAGE> continuing prose on same line."
    analysis = analyze_page_markers(text)
    assert len(analysis.markers) == 1
    marker = analysis.markers[0]
    assert marker.kind == PageMarkerKind.SGML
    assert marker.text == "<PAGE>"
    cleaned = strip_page_markers(text, analysis)
    assert "<PAGE>" not in cleaned
    assert "Heading line" in cleaned
    assert "continuing prose" in cleaned


def test_letter_number_preserved_by_default_without_sequence() -> None:
    text = "F-1\nSome prospectus text.\n"
    analysis = analyze_page_markers(text)
    assert len(analysis.markers) == 0  # not detected by default

    # Explicit allow
    analysis_allowed = analyze_page_markers(text, allow_letter_number=True)
    assert len(analysis_allowed.markers) == 1
    assert analysis_allowed.markers[0].kind == PageMarkerKind.LETTER_NUMBER
    assert analysis_allowed.markers[0].page_number == 1
    assert analysis_allowed.decisions[0].action == PageMarkerAction.REMOVE


def test_letter_number_in_sequence_is_removed() -> None:
    text = "-1-\n-2-\n-3-\nF-4\n"
    analysis = analyze_page_markers(text, allow_letter_number=True)
    assert len(analysis.markers) == 4
    assert all(d.action == PageMarkerAction.REMOVE for d in analysis.decisions)


def test_non_overlapping_spans_ordered() -> None:
    text = "-1-\nPage 2\n2 of 125\n<PAGE>     3\n"
    markers = find_page_markers(text)
    assert len(markers) == 4
    assert [m.page_number for m in markers] == [1, 2, 2, 3]
    for m in markers:
        assert text[m.start : m.end] == m.text


def test_strip_page_markers_cleans_text() -> None:
    text = (
        "ITEM 1. BUSINESS\n-1-\nWe build widgets.\nPage 2 of 10\nITEM 2. PROPERTIES\n"
    )
    cleaned = strip_page_markers(text)
    assert "-1-" not in cleaned
    assert "Page 2 of 10" not in cleaned
    assert "ITEM 1. BUSINESS" in cleaned
    assert "We build widgets." in cleaned
    assert "ITEM 2. PROPERTIES" in cleaned


def test_strip_page_markers_empty() -> None:
    assert strip_page_markers("") == ""
    assert analyze_page_markers("").markers == ()


def test_dataclasses_frozen() -> None:
    marker = PageMarker(
        start=0, end=4, text="-1-", kind=PageMarkerKind.DASHED_NUMBER, page_number=1
    )
    with pytest.raises(AttributeError):
        marker.start = 10
