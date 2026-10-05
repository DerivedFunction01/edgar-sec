"""Repeated header/footer classification and the mechanics behind it."""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.page_markers.candidates import line_offsets
from edgar_sec.engine.document.page_markers.models import (
    PageMarker,
    PageMarkerAction,
    PageMarkerKind,
)
from edgar_sec.engine.document.page_markers.templates import (
    LOCAL_DENSITY,
    MAX_FURNITURE_CHARS,
    MAX_FURNITURE_LINES,
    PERSISTENT_MIN_ANCHORS,
    PERSISTENT_MIN_CLUSTERS,
    Observation,
    analyze_repeating_headers,
    clean_template,
    clusters,
    collect_window,
    eligible_line,
    is_table_tag,
    merge_observations,
)


def _marker(start_line: int, page_number: int | None = None) -> PageMarker:
    return PageMarker(
        start=start_line * 10,
        end=start_line * 10 + 5,
        text="<PAGE>",
        kind=PageMarkerKind.SGML,
        page_number=page_number,
        start_line=start_line,
        end_line=start_line,
    )


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


def test_clean_template_collapses_whitespace_and_cases() -> None:
    assert clean_template("  ABC   CORP  ") == "abc corp"


def test_clean_template_masks_an_inline_page_label() -> None:
    # The label is replaced by " page #", leaving the preceding space; collapsing it
    # would change every id already derived from these templates.
    assert clean_template("ABC CORP page 12") == "abc corp  page #"


def test_clean_template_masks_a_trailing_label_only_when_words_remain() -> None:
    assert clean_template("Notes to consolidated financial statements 12") == (
        "notes to consolidated financial statements #"
    )
    assert clean_template("Exhibit 99") == "exhibit 99"


def test_clean_template_masks_a_namespaced_label() -> None:
    assert clean_template("Notes to statements F-3") == "notes to statements #"


def test_table_tags_are_recognized_in_either_case() -> None:
    assert is_table_tag("<TABLE>") is True
    assert is_table_tag("</table>") is True
    assert is_table_tag("<table class='x'>") is False


def test_an_empty_line_and_a_contents_line_are_ineligible() -> None:
    assert eligible_line("", set(), 0, None, allow_table=False) is False
    assert eligible_line("PART I ....... 1", {3}, 3, None, allow_table=False) is False


def test_a_bare_table_tag_is_eligible_only_when_table_furniture_is_admitted() -> None:
    assert eligible_line("<TABLE>", set(), 0, None, allow_table=False) is False
    assert eligible_line("<TABLE>", set(), 0, None, allow_table=True) is True


def test_a_line_inside_a_table_is_refused_unless_admitted() -> None:
    assert eligible_line("Item  1", set(), 0, "table", allow_table=False) is False
    assert eligible_line("Item  1", set(), 0, "table", allow_table=True) is True


def test_a_standalone_tag_and_a_sentence_are_never_furniture() -> None:
    assert eligible_line("<p>", set(), 0, None, allow_table=False) is False
    sentence = "This is a long sentence that reads as prose and not as furniture."
    assert eligible_line(sentence, set(), 0, None, allow_table=False) is False


def test_a_tag_carrying_a_spaced_attribute_is_a_furniture_candidate() -> None:
    # The standalone-tag test admits only an attribute-free tag name, so `<font size=2>`
    # is neither refused as a tag nor treated as prose.
    assert eligible_line("<font size=2>", set(), 0, None, allow_table=False) is True
    lines = ["<PAGE>", "<font size=2>", "Body"]
    assert collect_window(lines, 0, 1, {0}) == [
        (1, "<font size=2>"),
        (2, "Body"),
    ]


def test_a_very_long_line_is_never_furniture() -> None:
    line = "ACME " * 40
    assert eligible_line(line, set(), 0, None, allow_table=False) is False


def test_a_window_stops_at_the_next_boundary() -> None:
    lines = ["<PAGE>", "ABC CORP", "Body", "<PAGE>", "ABC CORP"]
    window = collect_window(lines, 0, 1, {0, 3})
    assert [index for index, _line in window] == [1, 2]


def test_a_window_steps_over_a_contiguous_boundary_cluster() -> None:
    lines = ["<PAGE>", "<PAGE>", "ABC CORP", "Body"]
    window = collect_window(lines, 0, 1, {0, 1})
    assert [index for index, _line in window] == [2, 3]


def test_a_window_skips_blank_lines_and_stops_at_a_standalone_tag() -> None:
    lines = ["<PAGE>", "", "ABC CORP", "", "<p>", "Body"]
    window = collect_window(lines, 0, 1, {0})
    assert [index for index, _line in window] == [2]


def test_a_window_is_bounded_in_lines() -> None:
    lines = ["<PAGE>", *(f"Line {i}" for i in range(20))]
    window = collect_window(lines, 0, 1, {0})
    assert len(window) == MAX_FURNITURE_LINES


def test_a_window_is_bounded_in_characters() -> None:
    lines = ["<PAGE>", *("x" * 300 for _ in range(8))]
    window = collect_window(lines, 0, 1, {0})
    assert sum(len(line) for _index, line in window) <= MAX_FURNITURE_CHARS


def test_a_window_stops_at_a_table_when_table_furniture_is_refused() -> None:
    lines = ["<PAGE>", "<TABLE>", "Item", "</TABLE>", "Body"]
    assert collect_window(lines, 0, 1, {0}) == []


def test_a_window_takes_a_whole_table_when_admitted() -> None:
    lines = ["<PAGE>", "<TABLE>", "Item", "</TABLE>", "Body"]
    window = collect_window(lines, 0, 1, {0}, allow_table=True)
    assert [index for index, _line in window] == [1, 2, 3, 4]


def test_a_window_reads_a_table_backwards_for_the_footer_side() -> None:
    lines = ["Body", "<TABLE>", "Item", "</TABLE>", "<PAGE>"]
    window = collect_window(lines, 4, -1, {4}, allow_table=True)
    assert [index for index, _line in window] == [3, 2, 1, 0]


def _obs(anchor_position: int) -> Observation:
    return Observation(
        "header", 0, "acme corp", anchor_position, "ACME CORP", anchor_position, 0
    )


def test_clusters_split_on_an_anchor_gap() -> None:
    members = [_obs(position) for position in (0, 1, 5, 6)]
    grouped = clusters(members)
    assert [(start, end) for _m, start, end, _d in grouped] == [(0, 1), (5, 6)]


def test_cluster_density_is_the_fraction_of_anchors_present() -> None:
    grouped = clusters([_obs(0), _obs(1), _obs(2)])
    assert grouped[0][3] == 1.0
    sparse = clusters([_obs(0), _obs(1), _obs(3)])
    assert sparse[0][3] == pytest.approx(0.75)


def test_merging_splits_a_span_around_an_unbacked_body_line() -> None:
    lines = ["ACME", "body sentence", "ACME"]
    offsets = line_offsets(lines)
    observations = [
        Observation("header", 0, "acme", index, line, 0, 0)
        for index, line in ((0, "ACME"), (2, "ACME"))
    ]
    ranges = merge_observations(observations, lines, offsets)
    assert [start for start, _end, _s, _e, _side in ranges] == [0, 2]


def test_merging_keeps_adjacent_backed_lines_in_one_span() -> None:
    lines = ["ACME", "CORP", "body"]
    offsets = line_offsets(lines)
    observations = [
        Observation("header", 0, "acme", index, line, 0, 0)
        for index, line in ((0, "ACME"), (1, "CORP"))
    ]
    ranges = merge_observations(observations, lines, offsets)
    assert ranges == [(0, 1, 0, 9, "header")]


def test_nothing_is_analysed_below_three_deduplicated_anchors() -> None:
    text = _paged(2, header="ABC CORP")
    templates, markers, decisions = analyze_repeating_headers(
        text, [_marker(0), _marker(3)]
    )
    assert (templates, markers, decisions) == ((), [], [])


def test_asymmetric_anchors_require_both_sides_below_three() -> None:
    # Four header and two footer anchors: the guard is max(header, footer) < 3, so the
    # larger side keeps the analysis alive.
    text = _paged(4, header="ABC CORP", footer="Confidential")
    templates, _markers, _decisions = analyze_repeating_headers(
        text,
        [_marker(index * 3) for index in range(4)],
        header_anchors=[0, 3, 6, 9],
        footer_anchors=[2, 5],
    )
    assert templates
    assert all(evidence.side in {"header", "footer"} for evidence in templates)


def test_a_dense_repeated_banner_is_recovered_and_marked_removable() -> None:
    text = _paged(4, header="ABC CORP")
    templates, markers, decisions = analyze_repeating_headers(
        text, [_marker(index * 3) for index in range(4)]
    )
    assert {evidence.template for evidence in templates} == {"abc corp"}
    assert [marker.text for marker in markers] == ["ABC CORP"] * 4
    assert all(marker.kind == PageMarkerKind.REPEATING_HEADER for marker in markers)
    assert all(decision.action == PageMarkerAction.REMOVE for decision in decisions)
    assert all(decision.reason == "repeating_furniture_block" for decision in decisions)


def test_a_line_observed_from_both_sides_is_claimed_once() -> None:
    # A banner between two breaks is observed by both sides but claimed once, which is
    # why observations exceed markers.
    text = _paged(4, header="ABC CORP")
    templates, markers, _decisions = analyze_repeating_headers(
        text, [_marker(index * 3) for index in range(4)]
    )
    observed = sum(evidence.occurrences for evidence in templates)
    assert {evidence.side for evidence in templates} == {"header", "footer"}
    assert observed > len(markers)
    assert len(markers) == 4
    assert len({(marker.start, marker.end) for marker in markers}) == len(markers)


def test_header_and_footer_furniture_are_recovered_separately() -> None:
    text = _paged(4, header="ABC CORP", footer="Confidential footer")
    _templates, markers, _decisions = analyze_repeating_headers(
        text, [_marker(index * 4) for index in range(4)]
    )
    assert {marker.text for marker in markers} == {"ABC CORP", "Confidential footer"}
    assert len(markers) == 8


def test_a_repeated_banner_on_the_header_side_is_boilerplate() -> None:
    text = _paged(5, header="ABC CORP")
    templates, _markers, _decisions = analyze_repeating_headers(
        text, [_marker(index * 3) for index in range(5)]
    )
    header = next(item for item in templates if item.side == "header")
    assert header.role == "boilerplate"
    assert header.retention == "remove_all"
    # One per page anchor, plus one from the virtual document-start boundary the header
    # side gains at three anchors.
    assert header.occurrences == 6
    assert header.presence == 1.0
    assert header.kind == PageMarkerKind.REPEATING_HEADER


def test_a_block_carries_its_line_span_and_block_size_as_evidence() -> None:
    text = _paged(
        4,
        header="ABC CORP\nFOR THE YEAR END DECEMBER 31, 2025\nNotes to statements",
    )
    _templates, markers, _decisions = analyze_repeating_headers(
        text, [_marker(index * 5) for index in range(4)]
    )
    assert markers
    assert all(marker.end_line - marker.start_line + 1 == 3 for marker in markers)
    assert all(
        any(item.startswith("lines:") for item in marker.evidence) for marker in markers
    )


def test_a_sparse_table_of_furniture_is_not_recovered_without_table_admission() -> None:
    pages = []
    for index in range(1, 5):
        pages.append(
            f"{index}\n<PAGE>\n<TABLE>\nRepeated table text\n</TABLE>\nBody {index}"
        )
    text = "\n".join(pages)
    templates, markers, _decisions = analyze_repeating_headers(
        text, [_marker(index * 5) for index in range(4)]
    )
    assert all(evidence.template != "repeated table text" for evidence in templates)
    assert markers == []


def test_the_asymmetric_anchor_guard_needs_all_four_thresholds_together() -> None:
    assert (LOCAL_DENSITY, PERSISTENT_MIN_ANCHORS, PERSISTENT_MIN_CLUSTERS) == (
        0.65,
        8,
        3,
    )


def test_a_document_with_no_furniture_returns_no_templates() -> None:
    text = _paged(5)
    templates, markers, _decisions = analyze_repeating_headers(
        text, [_marker(index * 2) for index in range(5)]
    )
    assert templates == ()
    assert markers == []
