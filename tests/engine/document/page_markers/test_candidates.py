"""Candidate classification, layout evidence, and run admission."""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.page_markers.candidates import (
    all_candidates,
    candidate_template,
    classify_candidate,
    cluster_is_table_like,
    firm_markers,
    has_numeric_data_shape,
    line_for_offset,
    line_offsets,
    looks_like_prose,
    marker_for_candidate,
    promote_groups,
    prose_stop_words,
    toc_lines,
)
from edgar_sec.engine.document.page_markers.models import (
    PageCandidate,
    PageMarkerKind,
)


def _cand(line: str, index: int = 0) -> PageCandidate | None:
    return classify_candidate(line, index, 0)


def test_pipe_header_line_classifies_as_a_trailing_number() -> None:
    candidate = _cand("Apple Inc. | 2025 Form 10-K | 1")
    assert candidate is not None
    assert candidate.value == 1
    assert candidate.family == PageMarkerKind.TRAILING_NUMBER
    assert candidate.text == "Apple Inc. | 2025 Form 10-K | 1"


@pytest.mark.parametrize(
    ("line", "value", "family"),
    [
        ("- 3 -", 3, PageMarkerKind.DASHED_NUMBER),
        ("| 4 |", 4, PageMarkerKind.PIPE_NUMBER),
        ("(5)", 5, PageMarkerKind.PAREN_NUMBER),
        ("7.", 7, PageMarkerKind.DOTTED_NUMBER),
        ("9", 9, PageMarkerKind.BARE_NUMBER),
        ("xiv", 14, PageMarkerKind.ROMAN_NUMBER),
    ],
)
def test_wrapped_and_bare_labels_carry_their_own_family(
    line: str, value: int, family: str
) -> None:
    candidate = _cand(line)
    assert candidate is not None
    assert candidate.value == value
    assert candidate.family == family


def test_roman_and_arabic_dash_labels_land_in_different_namespaces() -> None:
    assert _cand("- iv -").namespace == "roman"
    assert _cand("- 4 -").namespace == "arabic"


def test_namespaced_and_appendix_labels_carry_their_namespace() -> None:
    exhibit = _cand("F-3")
    assert exhibit is not None
    assert (exhibit.namespace, exhibit.value) == ("F", 3)
    appendix = _cand("A-IV")
    assert appendix is not None
    assert (appendix.namespace, appendix.value, appendix.family) == (
        "A",
        4,
        PageMarkerKind.APPENDIX_ROMAN,
    )


def test_letter_number_can_be_refused_by_the_caller() -> None:
    assert _cand("F-3") is not None
    assert classify_candidate("A-IV", 0, 0, allow_letter_number=False) is None


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        "<PAGE>",
        "</PAGE>",
        "PART I",
        "ITEM 1A.",
        "EXHIBIT 99",
        "NOTE 12",
    ],
)
def test_structural_lines_are_refused_before_any_label_shape_is_tried(
    line: str,
) -> None:
    assert _cand(line) is None


@pytest.mark.parametrize(
    "line",
    [
        "Total revenue              $ 1,234,567    $ 2,345,678",
        "Operating margin  12.5%  10.0%",
        "Item                          2024        2023",
    ],
)
def test_financial_rows_are_refused_as_page_labels(line: str) -> None:
    assert has_numeric_data_shape(line) is True
    assert _cand(line) is None


def test_a_long_prose_line_is_not_a_label() -> None:
    line = "This is a long sentence that a reader would call prose and not a label."
    assert looks_like_prose(line) is True
    assert {"this", "is", "and", "would"} <= prose_stop_words(line)
    assert looks_like_prose("Item") is False


def test_prose_needs_both_a_length_and_a_grammar_signal() -> None:
    assert len(prose_stop_words("the of and to")) >= 3
    assert looks_like_prose("the of and") is False


def test_candidate_template_masks_arabic_and_roman_values() -> None:
    assert candidate_template("Page 12 of 20") == "page # of #"
    assert candidate_template("Appendix xiv") == "appendix #"
    assert candidate_template("Apple Inc. | 2025 Form 10-K | 1") == (
        "apple inc. | # form #-k | #"
    )


def test_line_offsets_address_the_start_of_each_line() -> None:
    offsets = line_offsets(["ab", "cd", "ef"])
    assert offsets == [0, 3, 6]
    assert line_for_offset(offsets, 0) == 0
    assert line_for_offset(offsets, 3) == 1
    assert line_for_offset(offsets, 99) == 2


def test_firm_markers_claim_a_span_once_and_report_line_occupancy() -> None:
    markers, spans, lines = firm_markers("<PAGE>\nITEM 1. BUSINESS\n</PAGE>\n", "ascii")
    assert [marker.kind for marker in markers] == [
        PageMarkerKind.SGML,
        PageMarkerKind.SGML,
    ]
    assert len(spans) == 2
    assert lines == {0, 2}
    assert all(marker.evidence == ("firm_pattern",) for marker in markers)


def test_firm_markers_read_page_and_count_from_a_page_of_total_line() -> None:
    markers, _spans, _lines = firm_markers("Page 4 of 12\n", "ascii")
    assert markers[0].kind == PageMarkerKind.PAGE_NUMBER_OF_TOTAL
    assert (markers[0].page_number, markers[0].page_count) == (4, 12)


def test_firm_markers_lower_their_confidence_for_an_unproven_namespace() -> None:
    markers, _spans, _lines = firm_markers("F-3\n", "ascii")
    assert markers[0].kind == PageMarkerKind.LETTER_NUMBER
    assert markers[0].namespace == "F"
    assert markers[0].confidence == 0.7


def test_letter_number_firm_markers_are_skipped_when_refused() -> None:
    markers, _spans, _lines = firm_markers("F-3\n", "ascii", allow_letter_number=False)
    assert markers == []


def test_anchored_scan_examines_only_the_lines_near_each_anchor() -> None:
    block = [
        "<PAGE>",
        "1",
        *(["padding"] * 10),
        "9",
        *(["padding"] * 10),
        "2",
        "<PAGE>",
    ]
    text = "\n".join(block * 2)
    anchors = {
        index for index, line in enumerate(text.splitlines()) if line == "<PAGE>"
    }
    found = all_candidates(text, anchors, anchors=anchors)
    lines = {candidate.start_line for candidate in found}
    assert 1 in lines
    assert 23 in lines
    assert 12 not in lines


def test_anchorless_scan_skips_occupied_and_excluded_lines() -> None:
    text = "1\n2\n3\n4\n"
    found = all_candidates(text, {0}, excluded_lines={1})
    assert [candidate.start_line for candidate in found] == [2, 3]


def test_a_dense_burst_of_same_shaped_numbers_reads_as_a_table() -> None:
    text = "\n".join(str(index) for index in range(1, 12))
    found = all_candidates(text, set())
    assert len(found) == 11
    assert cluster_is_table_like(found) is True


def test_a_tight_inline_page_cluster_is_exempt_from_the_table_guess() -> None:
    text = "\n".join(f"continued on page {i} here" for i in range(1, 8))
    found = all_candidates(text, set())
    assert found
    assert all(
        candidate.family == PageMarkerKind.INLINE_PAGE_NUMBER for candidate in found
    )
    assert cluster_is_table_like(found) is False


def test_too_few_members_is_reported_as_such_and_admits_nothing() -> None:
    candidates = [c for c in (_cand("1", i) for i in range(2)) if c is not None]
    markers, runs, accepted, rejections = promote_groups(candidates, anchored=True)
    assert (markers, runs, accepted) == ([], [], [])
    assert "fewer_than_min_members" in rejections


def test_a_validated_anchored_run_admits_its_members_with_evidence() -> None:
    candidates = [c for c in (_cand(str(i), i * 2) for i in range(1, 5)) if c]
    markers, runs, accepted, rejections = promote_groups(candidates, anchored=True)
    assert [run.strategy for run in runs] == ["anchor_relative:healed"]
    assert [marker.page_number for marker in markers] == [1, 2, 3, 4]
    assert all("anchor_relative_sequence" in marker.evidence for marker in markers)
    assert all(
        any(evidence.startswith("monotone:") for evidence in marker.evidence)
        for marker in markers
    )
    assert len(accepted) == 4
    assert rejections == ()


def test_marker_for_candidate_carries_the_candidate_identity_forward() -> None:
    candidate = _cand("- 3 -", 4)
    assert candidate is not None
    marker = marker_for_candidate(candidate, 0.8, ("anchorless_sequence",))
    assert (marker.start, marker.end) == (candidate.start, candidate.end)
    assert marker.namespace == candidate.namespace
    assert marker.representation == "ascii"


def test_toc_lines_excludes_nothing_without_a_resolver() -> None:
    assert toc_lines("PART I ....... 1\n") == set()


def test_toc_lines_excludes_the_span_the_caller_located() -> None:
    class Span:
        start_line = 2
        end_line = 5

    assert toc_lines("text", lambda _text: Span()) == {2, 3, 4}


def test_toc_lines_excludes_nothing_when_the_resolver_finds_no_span() -> None:
    assert toc_lines("text", lambda _text: None) == set()
