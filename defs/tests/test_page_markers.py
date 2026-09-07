"""Contract tests for the retained ASCII/string page-marker pipeline."""

from __future__ import annotations

from defs.sec_forms.page_markers import (
    PageMarkerAction,
    PageMarkerKind,
    analyze_page_markers,
    apply_text_policy,
    strip_page_markers,
)


def test_sgml_page_markers_are_detected_and_removed() -> None:
    text = "<PAGE>\nITEM 1. BUSINESS\n</PAGE>\n"
    analysis = analyze_page_markers(text)

    assert len(analysis.markers) == 2
    assert all(marker.kind == PageMarkerKind.SGML for marker in analysis.markers)
    assert all(
        decision.action == PageMarkerAction.REMOVE for decision in analysis.decisions
    )
    assert "<PAGE>" not in strip_page_markers(text, analysis)


def test_repeating_numeric_page_sequence_is_analyzed() -> None:
    text = "Cover\n<PAGE> 1\nBody\n<PAGE> 2\n<PAGE> 3\n"
    analysis = analyze_page_markers(text)

    assert [marker.page_number for marker in analysis.markers] == [1, 2, 3]


def test_page_policy_operates_on_text_frame_without_dom() -> None:
    text = "Header\n<PAGE> 1\nBody\n<PAGE> 2\n"
    normalized, analysis, artifacts, templates, _ = apply_text_policy(text)

    assert analysis.representation == "ascii"
    assert artifacts
    assert not templates
    assert "<PAGE>" not in normalized
