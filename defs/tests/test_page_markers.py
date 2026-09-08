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


def test_repeating_furniture_after_firm_break_uses_break_anchors() -> None:
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


def test_unnumbered_page_breaks_anchor_repeating_header() -> None:
    text = "\n".join(
        f"<PAGE>\nABC CORP\nNotes to consolidated financial statements\nBody {i}"
        for i in range(1, 5)
    )

    analysis = analyze_page_markers(text, {"toc_lines": {-1}})

    repeated = [
        marker
        for marker in analysis.markers
        if marker.kind == PageMarkerKind.REPEATING_HEADER
    ]
    assert len(repeated) == 4
    assert all(marker.end_line > marker.start_line for marker in repeated)
    assert all(marker.page_number is None for marker in repeated)


def test_multiline_furniture_removes_block_and_preserves_body() -> None:
    pages = []
    for index in range(1, 5):
        pages.extend(
            [
                str(index),
                "<PAGE>",
                "ABC CORP",
                "FOR THE YEAR END DECEMBER 31, 2025",
                "Notes to consolidated financial statements",
                "",
                f"The company provides operating information for page {index}.",
            ]
        )
    text = "\n".join(pages)

    normalized, analysis, _, _, _ = apply_text_policy(text)

    blocks = [
        marker
        for marker in analysis.markers
        if marker.kind == PageMarkerKind.REPEATING_HEADER
    ]
    assert len(blocks) == 4
    assert all(marker.end_line - marker.start_line + 1 == 3 for marker in blocks)
    assert "ABC CORP" not in normalized
    assert "operating information for page 4" in normalized


def test_local_section_run_is_not_lost_to_document_denominator() -> None:
    pages = []
    for index in range(1, 21):
        pages.extend(
            [
                str(index),
                "<PAGE>",
                "Long filing body",
                "",
                "Local appendix banner" if 11 <= index <= 15 else f"Body {index}",
            ]
        )
    analysis = analyze_page_markers("\n".join(pages), {"toc_lines": {-1}})

    assert any(
        evidence.template == "local appendix banner" and evidence.occurrences == 5
        for evidence in analysis.header_footer_templates
    )


def test_section_header_keeps_first_occurrence_per_local_section() -> None:
    pages = []
    for index in range(1, 7):
        title = "PART I" if index <= 3 else "Notes to consolidated financial statements"
        pages.extend([str(index), "<PAGE>", title, "", f"Body {index}"])
    text = "\n".join(pages)

    analysis = analyze_page_markers(text, {"toc_lines": {-1}})
    normalized, _, _, _, _ = apply_text_policy(text, analysis=analysis)

    assert sum(line == "PART I" for line in normalized.splitlines()) == 1
    assert (
        sum(
            line == "Notes to consolidated financial statements"
            for line in normalized.splitlines()
        )
        == 1
    )
    assert any(
        evidence.role == "section_header"
        and evidence.retention == "keep_first_per_cohort"
        for evidence in analysis.header_footer_templates
    )


def test_footer_uses_numeric_label_before_structural_break() -> None:
    pages = []
    for index in range(1, 5):
        pages.extend(
            [
                "<PAGE>",
                "ABC CORP",
                f"Body {index}",
                "Confidential footer",
                f"Page {index}",
            ]
        )
    analysis = analyze_page_markers("\n".join(pages), {"toc_lines": {-1}})

    footers = [
        marker
        for marker in analysis.markers
        if marker.kind == PageMarkerKind.REPEATING_FOOTER
    ]
    assert [marker.text for marker in footers] == [
        "Confidential footer",
        "Confidential footer",
        "Confidential footer",
        "Confidential footer",
    ]


def test_ascii_table_units_are_not_furniture_candidates() -> None:
    text = "\n".join(
        f"<PAGE>\n<TABLE>\nRepeated table text\n</TABLE>\nBody {index}"
        for index in range(1, 5)
    )

    analysis = analyze_page_markers(text, {"toc_lines": {-1}})

    assert not any(
        marker.kind == PageMarkerKind.REPEATING_HEADER for marker in analysis.markers
    )


def test_cover_furniture_before_first_break_is_removed() -> None:
    pages = ["Cover title", "Table of Contents", ""]
    for index in range(1, 5):
        pages.extend(
            [
                str(index),
                "<PAGE>",
                "Table of Contents",
                "",
                f"Body {index}",
            ]
        )
    text = "\n".join(pages)

    normalized, analysis, _, _, _ = apply_text_policy(text)

    repeated = [
        marker
        for marker in analysis.markers
        if marker.kind == PageMarkerKind.REPEATING_HEADER
    ]
    assert len(repeated) >= 4
    assert any(marker.start_line == 1 for marker in repeated)
    assert sum(line == "Table of Contents" for line in normalized.splitlines()) == 0
    assert "Cover title" in normalized
    assert "Body 4" in normalized


def test_trailing_footer_after_last_break_is_removed() -> None:
    pages = []
    for index in range(1, 5):
        pages.extend(
            [
                str(index),
                "<PAGE>",
                "ABC CORP",
                f"Body {index}",
                "Confidential footer",
            ]
        )
    pages.append("Confidential footer")
    text = "\n".join(pages)

    analysis = analyze_page_markers(text, {"toc_lines": {-1}})

    footers = [
        marker
        for marker in analysis.markers
        if marker.kind == PageMarkerKind.REPEATING_FOOTER
    ]
    assert len(footers) >= 4
    assert footers[-1].end_line == len(text.splitlines()) - 1
    assert "Confidential footer" in footers[-1].text
