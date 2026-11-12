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
from edgar_sec.engine.document.page_markers.content_lines import (
    has_cross_reference,
    is_content_line,
)
from edgar_sec.engine.document.page_markers.models import (
    PageCandidate,
    PageMarkerKind,
)


def _cand(line: str, index: int = 0) -> PageCandidate | None:
    return classify_candidate(line, index, 0)


def test_pipe_header_line_classifies_as_a_trailing_number() -> None:
    line = "Apple Inc. | 2025 Form 10-K | 1"
    candidate = _cand(line)
    assert candidate is not None
    assert candidate.value == 1
    assert candidate.family == PageMarkerKind.TRAILING_NUMBER
    assert candidate.text == line
    assert candidate.start == 0
    assert candidate.end == len(line)


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


# Specimen lines: iteration-2 census defect_5/defect_2 filings named per group.
@pytest.mark.parametrize(
    "line",
    [
        # Jurats: 0001104659-09-028708, 0000950123-09-040787, 0001104659-10-061548.
        "STATE OF NEW YORK   )",
        "COUNTY OF NEW YORK  )",
        "THE COMMONWEALTH OF MASSACHUSETTS  )",
        "County of Suffolk              )",
        ")ss:",
        ")  ss:",
        # Signature blocks: 0000950123-09-044722, 0000950144-03-008143, 0000895345-05-000821.
        "Title:  Group General Counsel",
        "Title:  Chief Financial Officer",
        "By:  LAMAR MEDIA CORP.,",
        "By:",
        "Name:  Kristin Jumper",
        "Name:   Ted Chang",
    ],
)
def test_jurat_and_signature_lines_are_content(line: str) -> None:
    assert is_content_line(line) is True


@pytest.mark.parametrize(
    "line",
    [
        # Schedule title: 0000930413-04-005468; ISIN line: defect_2 family D2-C specimen.
        "Schedule of Investments (unaudited) (continued)  September 30, 2004",
        "Schedule of Investments",
        "ISIN MHY271831056",
        # Statement titles and cross-references: defect_1 families A, C, E.
        "Notes to Financial Statements (Continued)  December 31, 2008",
        "Notes to the Consolidated Financial Statements",
        "CONSOLIDATED STATEMENTS OF OPERATIONS (Continued)",
        "See accompanying notes to financial statements.",
        "See Notes to Financial Statements",
        # Cross-references beyond the notes shapes: iteration-4 see-veto specimens.
        "See Accountants\u2019 Audit Report",
        "SEE INSTRUCTIONS BEFORE FILLING OUT!",
        "**SEE ITEM 4(b).",
        "See Note 1.",
        "Please see Note 1.",
        "See page A-3",
        "(See Note 3)",
    ],
)
def test_schedule_statement_and_identifier_lines_are_content(line: str) -> None:
    assert is_content_line(line) is True


@pytest.mark.parametrize(
    "line",
    [
        # A proxy running head is not a financial-statement title (defect_1 family F).
        "SERVISFIRST BANCSHARES, INC. - Notice of 2023 Annual Meeting of Stockholders and Proxy Statement",
        "Board of Directors",
        "Milwaukee, Wisconsin",
        "State Street Global Advisors  1 of 5",
        "Provisions of the Investment Company Act of 1940",
        # The veto keys on the bounded word: "see" inside a word is no reference.
        "Oversee the fund operations",
        "Seeley Industries, Inc.",
    ],
)
def test_running_heads_and_banners_are_not_content_lines(line: str) -> None:
    assert is_content_line(line) is False


@pytest.mark.parametrize("line", ["------", "============", "----", "——————"])
def test_a_rule_only_line_is_not_a_page_label_candidate(line: str) -> None:
    assert _cand(line) is None


@pytest.mark.parametrize(
    "line",
    [
        "See discussion on page 3",
        "Discussion (see page 3)",
        "See Note 1.",
        "Please see Note 1.",
    ],
)
def test_a_cross_reference_line_yields_no_candidate(line: str) -> None:
    # A sub-span label cut out of a cross-reference sentence would amputate prose.
    assert has_cross_reference(line) is True
    assert _cand(line) is None


def test_an_inline_page_of_total_does_not_cut_a_cross_reference_line() -> None:
    markers, _occupied, _lines = firm_markers("See page 2 of 9 pages\nBody\n", "ascii")
    assert not any(
        marker.kind == PageMarkerKind.PAGE_NUMBER_OF_TOTAL for marker in markers
    )


def test_an_inline_page_of_total_still_cuts_a_furniture_line() -> None:
    text = "ACME page 2 of 9 pages\nBody\n"
    markers, _occupied, _lines = firm_markers(text, "ascii")
    assert any(marker.kind == PageMarkerKind.PAGE_NUMBER_OF_TOTAL for marker in markers)


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


def test_firm_markers_read_page_and_count_with_trailing_pages_and_continuation() -> (
    None
):
    markers, _spans, lines = firm_markers(
        "[Continued on following page(s)] Page 1 of 4 Pages\n", "ascii"
    )
    assert len(markers) == 1
    assert markers[0].kind == PageMarkerKind.PAGE_NUMBER_OF_TOTAL
    assert (markers[0].page_number, markers[0].page_count) == (1, 4)
    assert lines == {0}


def test_firm_markers_extract_inline_page_of_total_and_preserve_columns() -> None:
    text = "CUSIP No.\t28134710A       \t\tPage 2 of 4 Pages\n"
    markers, _spans, lines = firm_markers(text, "ascii")
    assert len(markers) == 1
    assert markers[0].kind == PageMarkerKind.PAGE_NUMBER_OF_TOTAL
    assert (markers[0].page_number, markers[0].page_count) == (2, 4)
    assert text[markers[0].start : markers[0].end] == "       \t\tPage 2 of 4 Pages"
    assert lines == {0}


def test_firm_markers_skip_mid_sentence_prose_page_of_total() -> None:
    text = "The agreement is set forth on page 1 of 4 pages of Exhibit 10.\n"
    markers, _spans, lines = firm_markers(text, "ascii")
    assert len(markers) == 0
    assert lines == set()


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


def test_a_lone_heading_digit_is_not_admitted_without_a_repeated_line_shape() -> None:
    lines = [
        "1 Nature of Business",
        "2 Basis of Presentation",
        "3 Summary of Significant Accounting Policies",
    ]
    candidates = [c for c in (_cand(line, i * 2) for i, line in enumerate(lines)) if c]
    assert [c.family for c in candidates] == [PageMarkerKind.NUMBER_FIRST] * 3
    markers, runs, accepted, rejections = promote_groups(candidates, anchored=True)
    assert markers == []
    assert runs == []
    assert accepted == []
    assert "heading_runin_sub_span" in rejections


def test_a_repeated_running_head_refuses_its_trailing_numbers() -> None:
    lines = [f"ACME Corp Annual Report  {value}" for value in (1, 2, 3, 4)]
    candidates = [c for c in (_cand(line, i * 2) for i, line in enumerate(lines)) if c]
    assert candidates and all(
        c.family == PageMarkerKind.TRAILING_NUMBER for c in candidates
    )
    markers, runs, accepted, rejections = promote_groups(candidates, anchored=True)
    assert (markers, runs, accepted) == ([], [], [])
    assert "heading_runin_sub_span" in rejections


def test_a_repeated_number_first_running_head_refuses_its_numbers() -> None:
    lines = [f"{value}  ACME Corp Annual Report" for value in (1, 2, 3, 4)]
    candidates = [c for c in (_cand(line, i * 2) for i, line in enumerate(lines)) if c]
    assert candidates and all(
        c.family == PageMarkerKind.NUMBER_FIRST for c in candidates
    )
    markers, runs, accepted, rejections = promote_groups(candidates, anchored=True)
    assert (markers, runs, accepted) == ([], [], [])
    assert "heading_runin_sub_span" in rejections


def test_a_numbered_heading_sequence_refuses_its_digits() -> None:
    lines = [
        "1 Nature of Business and Basis of Presentation",
        "2 Basis of Presentation",
        "3 Summary of Significant Accounting Policies",
        "4 Recent Accounting Pronouncements",
    ]
    candidates = [c for c in (_cand(line, i * 2) for i, line in enumerate(lines)) if c]
    assert candidates and all(
        c.family == PageMarkerKind.NUMBER_FIRST for c in candidates
    )
    markers, runs, accepted, rejections = promote_groups(candidates, anchored=True)
    assert (markers, runs, accepted) == ([], [], [])
    assert "heading_runin_sub_span" in rejections


def test_a_short_loose_of_total_still_admits_its_numbers() -> None:
    lines = [f"{value} of 4" for value in (1, 2, 3, 4)]
    candidates = [c for c in (_cand(line, i * 2) for i, line in enumerate(lines)) if c]
    assert candidates and all(
        c.family == PageMarkerKind.NUMBER_FIRST for c in candidates
    )
    markers, _runs, _accepted, rejections = promote_groups(candidates, anchored=True)
    assert [marker.page_number for marker in markers] == [1, 2, 3, 4]
    assert "heading_runin_sub_span" not in rejections


def test_the_incorporation_cover_line_is_prose_under_the_guard() -> None:
    line = "(State or other jurisdiction of incorporation or organization)"
    assert looks_like_prose(line)


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


@pytest.mark.parametrize(
    "line",
    [
        # Letter subject and addressee lines: 0001477932-10-000251 (CORRESP).
        "Re: Acquisition Capital Group, Inc.",
        "Mr. Tom Kluck",
        "Dr. Jane Smith",
        # Footnote line glued to a bare page number: 0000932471-04-001270.
        "*For underlying funds; annualized.",
    ],
)
def test_letter_and_footnote_lines_are_content(line: str) -> None:
    assert is_content_line(line) is True
