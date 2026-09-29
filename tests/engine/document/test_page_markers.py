"""Unit and contract tests for edgar_sec.engine.document.page_markers."""

from __future__ import annotations

from edgar_sec.engine.document.page_markers import (
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


def test_namespaced_sgml_page_marker_is_removed() -> None:
    text = "before\n<page>F-15\nafter\n"
    analysis = analyze_page_markers(text)
    normalized, *_ = apply_text_policy(text, analysis)

    assert len(analysis.markers) == 1
    assert analysis.markers[0].kind == PageMarkerKind.SGML
    assert "F-15" not in normalized


def test_page_policy_operates_on_text_frame() -> None:
    text = "Header\n<PAGE> 1\nBody\n<PAGE> 2\n"
    normalized, analysis, artifacts, templates, _ = apply_text_policy(text)

    assert analysis.representation == "ascii"
    assert artifacts
    assert not templates
    assert "<PAGE>" not in normalized


def test_repeating_furniture_after_firm_break() -> None:
    text = (
        "1\n<PAGE>\nTable of Contents\nBody one\n"
        "2\n<PAGE>\nTable of Contents\nBody two\n"
        "3\n<PAGE>\nTable of Contents\nBody three\n"
    )

    analysis = analyze_page_markers(text)

    repeating = [
        marker
        for marker in analysis.markers
        if marker.kind == PageMarkerKind.REPEATING_HEADER
    ]
    assert [marker.text for marker in repeating] == [
        "Table of Contents",
        "Table of Contents",
        "Table of Contents",
    ]
