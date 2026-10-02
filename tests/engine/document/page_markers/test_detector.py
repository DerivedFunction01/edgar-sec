"""The detector entry points: what a document's own page claims are worth."""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.page_markers.detector import (
    analyze_page_markers,
    find_page_markers,
    is_page_marker_line,
)
from edgar_sec.engine.document.page_markers.models import (
    PageMarkerAction,
    PageMarkerKind,
    PageMarkerTerminalState,
)

NO_TOC = {"toc_lines": frozenset({-1})}


def _paged(
    pages: int, header: str = "", footer: str = "", label: str = "<PAGE>"
) -> str:
    lines: list[str] = []
    for index in range(1, pages + 1):
        lines.append(label)
        if header:
            lines.append(header)
        lines.append(f"Body {index}")
        if footer:
            lines.append(footer)
    return "\n".join(lines)


def test_an_empty_document_reports_no_visible_labels() -> None:
    analysis = analyze_page_markers("")
    assert analysis.markers == ()
    assert analysis.terminal_state is PageMarkerTerminalState.NO_VISIBLE_LABELS
    assert analysis.coordinate_frame == "text"


def test_sgml_page_tags_are_detected_and_removed() -> None:
    text = "<PAGE>\nITEM 1. BUSINESS\n</PAGE>\n"
    analysis = analyze_page_markers(text)
    assert len(analysis.markers) == 2
    assert all(marker.kind == PageMarkerKind.SGML for marker in analysis.markers)
    assert all(
        decision.action == PageMarkerAction.REMOVE for decision in analysis.decisions
    )


def test_the_sgml_line_form_carries_no_namespace_or_page_number() -> None:
    # `<page>F-15</page>` matches the SGML line form, whose `page` group accepts
    # the whole `F-15` token; a non-numeric group is therefore read as "no page
    # number" and the namespace defaults to arabic. The token is still removed,
    # because the SGML tag is what authorized the removal.
    analysis = analyze_page_markers("before\n<page>F-15\nafter\n")
    assert len(analysis.markers) == 1
    assert analysis.markers[0].kind == PageMarkerKind.SGML
    assert analysis.markers[0].page_number is None
    assert analysis.markers[0].namespace == "arabic"
    assert analysis.decisions[0].action == PageMarkerAction.REMOVE


def test_a_repeating_numeric_page_sequence_is_analyzed() -> None:
    analysis = analyze_page_markers("Cover\n<PAGE> 1\nBody\n<PAGE> 2\n<PAGE> 3\n")
    assert [
        marker.page_number for marker in analysis.markers if marker.page_number
    ] == [
        1,
        2,
        3,
    ]


def test_a_boundary_token_is_normalized_rather_than_removed() -> None:
    analysis = analyze_page_markers("(PAGE)\n(PAGE)\n(PAGE)\n")
    decisions = [
        item
        for item in analysis.decisions
        if item.marker.kind == PageMarkerKind.BOUNDARY
    ]
    assert len(decisions) == 3
    assert {item.action for item in decisions} == {PageMarkerAction.NORMALIZE}
    assert {item.reason for item in decisions} == {"boundary_only_marker"}


def test_an_unproven_namespaced_label_is_preserved() -> None:
    analysis = analyze_page_markers("F-3\n")
    (decision,) = analysis.decisions
    assert decision.action == PageMarkerAction.PRESERVE
    assert decision.reason == "ambiguous_letter_number"


def test_a_namespaced_label_with_its_own_validated_run_is_removed() -> None:
    # `F-1`..`F-5` are firm labels in namespace F, and they validate as a run of
    # their own, so the namespace is trusted and the labels are removed rather
    # than preserved as ambiguous.
    text = "\n".join(f"F-{index}" for index in range(1, 6))
    analysis = analyze_page_markers(text, NO_TOC)
    assert {marker.namespace for marker in analysis.markers} == {"F"}
    assert all(
        decision.action == PageMarkerAction.REMOVE for decision in analysis.decisions
    )


def test_repeating_furniture_after_firm_breaks_uses_the_breaks_as_anchors() -> None:
    text = (
        "1\n<PAGE>\nTable of Contents\nBody one\n"
        "2\n<PAGE>\nTable of Contents\nBody two\n"
        "3\n<PAGE>\nTable of Contents\nBody three\n"
    )
    analysis = analyze_page_markers(text, NO_TOC)
    repeating = [
        marker
        for marker in analysis.markers
        if marker.kind == PageMarkerKind.REPEATING_HEADER
    ]
    assert [marker.text for marker in repeating] == ["Table of Contents"] * 3


def test_unnumbered_page_breaks_anchor_repeating_header() -> None:
    text = "\n".join(
        f"<PAGE>\nABC CORP\nNotes to consolidated financial statements\nBody {index}"
        for index in range(1, 5)
    )
    analysis = analyze_page_markers(text, NO_TOC)
    repeated = [
        marker
        for marker in analysis.markers
        if marker.kind == PageMarkerKind.REPEATING_HEADER
    ]
    assert len(repeated) == 4
    assert all(marker.end_line > marker.start_line for marker in repeated)
    assert all(marker.page_number is None for marker in repeated)


def test_a_multiline_furniture_block_removes_as_one_block() -> None:
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
    analysis = analyze_page_markers("\n".join(pages))
    blocks = [
        marker
        for marker in analysis.markers
        if marker.kind == PageMarkerKind.REPEATING_HEADER
    ]
    assert len(blocks) == 4
    assert all(marker.end_line - marker.start_line + 1 == 3 for marker in blocks)


def test_a_local_section_run_survives_the_document_denominator() -> None:
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
    analysis = analyze_page_markers("\n".join(pages), NO_TOC)
    assert any(
        evidence.template == "local appendix banner" and evidence.occurrences == 5
        for evidence in analysis.header_footer_templates
    )


def test_a_section_header_keeps_one_occurrence_per_local_cohort() -> None:
    pages = []
    for index in range(1, 7):
        title = "PART I" if index <= 3 else "Notes to consolidated financial statements"
        pages.extend([str(index), "<PAGE>", title, "", f"Body {index}"])
    analysis = analyze_page_markers("\n".join(pages), NO_TOC)
    assert any(
        evidence.role == "section_header"
        and evidence.retention == "keep_first_per_cohort"
        for evidence in analysis.header_footer_templates
    )


def test_footer_furniture_is_recovered_as_a_footer() -> None:
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
    analysis = analyze_page_markers("\n".join(pages), NO_TOC)
    footers = [
        marker
        for marker in analysis.markers
        if marker.kind == PageMarkerKind.REPEATING_FOOTER
    ]
    assert [marker.text for marker in footers] == ["Confidential footer"] * 4


def test_ascii_table_units_are_not_furniture_candidates() -> None:
    text = "\n".join(
        f"<PAGE>\n<TABLE>\nRepeated table text\n</TABLE>\nBody {index}"
        for index in range(1, 5)
    )
    analysis = analyze_page_markers(text, NO_TOC)
    assert not any(
        marker.kind == PageMarkerKind.REPEATING_HEADER for marker in analysis.markers
    )


def test_a_candidate_no_run_claimed_is_reported_not_removed() -> None:
    lonely = analyze_page_markers("1\n\nOne lone number\n", NO_TOC)
    assert lonely.markers == ()
    assert lonely.unresolved == ("0:1", "0:1")
    # No marker carries a page number, so the document is reported as carrying
    # no visible labels rather than as unresolved.
    assert lonely.terminal_state is PageMarkerTerminalState.NO_VISIBLE_LABELS


def test_an_unresolved_candidate_beside_a_validated_run_is_reported_unresolved() -> (
    None
):
    text = "\n".join(
        line
        for index in (1, 2, 3, 4, 5)
        for line in (f"{index}", "<PAGE>", f"Body {index}", "9")
    )
    analysis = analyze_page_markers(text, NO_TOC)
    assert analysis.page_number_runs
    assert analysis.unresolved
    assert analysis.terminal_state is PageMarkerTerminalState.UNRESOLVED


def test_a_candidate_seen_by_both_scans_is_reported_once_per_scan() -> None:
    # The anchored and anchorless scans each produce their own candidate list,
    # and both are reported. A caller reading `unresolved` as a set of lines
    # rather than a sequence of observations must therefore de-duplicate.
    text = "1\nBody\n2\nBody\n3\nBody\n"
    analysis = analyze_page_markers(text, NO_TOC)
    assert analysis.unresolved == (
        "0:1",
        "2:2",
        "4:3",
        "0:1",
        "2:2",
        "4:3",
    )


def test_rejections_are_reported_by_name() -> None:
    too_few = analyze_page_markers("1\n<PAGE>\n2\n", NO_TOC)
    assert "fewer_than_min_members" in too_few.rejection_diagnostics
    assert "provisional_validation_failed" in too_few.rejection_diagnostics
    dense = analyze_page_markers("1\nBody\n2\nBody\n3\nBody\n", NO_TOC)
    assert dense.rejection_diagnostics == ("table_like_cluster",)


def test_source_identity_from_the_context_is_recorded_on_the_result() -> None:
    analysis = analyze_page_markers("<PAGE>\nBody\n", {"source_identity": "abc123"})
    assert analysis.source_identity == "abc123"


def test_page_boundaries_exclude_recovered_furniture_spans() -> None:
    analysis = analyze_page_markers(_paged(4, header="ABC CORP"), NO_TOC)
    furniture = {
        (marker.start, marker.end)
        for marker in analysis.markers
        if marker.kind
        in {PageMarkerKind.REPEATING_HEADER, PageMarkerKind.REPEATING_FOOTER}
    }
    assert not furniture.intersection(analysis.page_boundaries)


def test_html_representation_is_refused_rather_than_scanned_as_markup() -> None:
    with pytest.raises(ValueError, match="does not accept representation='html'"):
        analyze_page_markers("<PAGE>Body</PAGE>", representation="html")


# --- find_page_markers -------------------------------------------------------


def test_find_page_markers_reports_spans_in_source_order() -> None:
    spans = find_page_markers("<PAGE>\nBody\n</PAGE>\n")
    assert [(span.kind, span.text) for span in spans] == [
        (PageMarkerKind.SGML, "<PAGE>"),
        (PageMarkerKind.SGML, "</PAGE>"),
    ]
    assert [span.start for span in spans] == sorted(span.start for span in spans)


def test_find_page_markers_reports_a_page_of_total_as_number_of_total() -> None:
    (span,) = find_page_markers("Page 4 of 12\n")
    assert span.kind == PageMarkerKind.NUMBER_OF_TOTAL
    assert (span.page_number, span.page_count) == (4, 12)


def test_find_page_markers_excludes_recovered_furniture() -> None:
    spans = find_page_markers(_paged(4, header="ABC CORP"))
    assert all(
        span.kind
        not in {PageMarkerKind.REPEATING_HEADER, PageMarkerKind.REPEATING_FOOTER}
        for span in spans
    )


# --- is_page_marker_line -----------------------------------------------------


@pytest.mark.parametrize(
    "line", ["<PAGE>", "</PAGE>", "(PAGE)", "[PAGE]", "Page 4", "- 3 -", "4 of 12"]
)
def test_a_firm_marker_line_is_recognized(line: str) -> None:
    assert is_page_marker_line(line) is True


@pytest.mark.parametrize("line", ["", "   ", "F-3", "Body text", "ITEM 1A."])
def test_a_line_that_is_not_a_firm_marker_is_refused(line: str) -> None:
    assert is_page_marker_line(line) is False


def test_a_namespaced_label_is_not_a_marker_line_on_its_shape_alone() -> None:
    assert is_page_marker_line("F-3") is False
