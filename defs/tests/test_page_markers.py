"""Contract and unit tests for shared page-marker analysis."""

from __future__ import annotations

import importlib

import pytest
from bs4 import BeautifulSoup

from defs.sec_forms.page_markers.headers import _slot_heading_members
from defs.sec_forms.page_markers.html import html_has_page_label_evidence
from defs.sec_forms.page_markers.sequence import heal_run
from defs.text.html import parse_html

pm_mod = importlib.import_module("defs.sec_forms.page_markers")

PageMarker = pm_mod.PageMarker
PageMarkerAction = pm_mod.PageMarkerAction
PageMarkerAnalysis = pm_mod.PageMarkerAnalysis
PageMarkerDecision = pm_mod.PageMarkerDecision
PageMarkerKind = pm_mod.PageMarkerKind
PageMarkerSpan = pm_mod.PageMarkerSpan
PageCandidate = pm_mod.PageCandidate
analyze_page_markers = pm_mod.analyze_page_markers
find_page_markers = pm_mod.find_page_markers
strip_page_markers = pm_mod.strip_page_markers
apply_html_page_decisions = pm_mod.apply_html_page_decisions
enrich_html_analysis = pm_mod.enrich_html_analysis


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
    assert len(analysis.markers) == 1
    assert analysis.markers[0].kind == PageMarkerKind.LETTER_NUMBER
    assert analysis.markers[0].page_number == 1
    assert analysis.decisions[0].action == PageMarkerAction.PRESERVE

    analysis_allowed = analyze_page_markers(text, allow_letter_number=True)
    assert len(analysis_allowed.markers) == 1
    assert analysis_allowed.markers[0].kind == PageMarkerKind.LETTER_NUMBER
    assert analysis_allowed.markers[0].page_number == 1
    assert analysis_allowed.decisions[0].action == PageMarkerAction.PRESERVE


def test_letter_number_in_sequence_is_removed() -> None:
    text = "-1-\n-2-\n-3-\nF-4\n"
    analysis = analyze_page_markers(text)
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


def test_ascii_anchor_relative_bare_numbers_are_promoted() -> None:
    text = """<PAGE>
1
Body text for page one.
<PAGE>
2
Body text for page two.
<PAGE>
3
Body text for page three."""
    analysis = analyze_page_markers(text)
    numbers = [marker for marker in analysis.markers if marker.page_number is not None]
    assert [marker.page_number for marker in numbers] == [1, 2, 3]
    assert numbers[0].kind == PageMarkerKind.BARE_NUMBER
    assert analysis.page_number_runs[0].strategy.startswith("anchor_relative")
    assert all(
        decision.action == PageMarkerAction.REMOVE for decision in analysis.decisions
    )


def test_ascii_anchorless_sequence_is_promoted() -> None:
    lines: list[str] = []
    for page in range(1, 4):
        lines.append(str(page))
        lines.extend(["Body content that is not a label."] * 9)
    analysis = analyze_page_markers("\n".join(lines))
    assert [marker.page_number for marker in analysis.markers] == [1, 2, 3]
    assert analysis.page_number_runs[0].strategy.startswith("anchorless")
    assert strip_page_markers(analysis.source_text, analysis) != analysis.source_text


def test_ascii_roman_and_boundary_only_markers() -> None:
    text = "\n".join(
        [
            "- i -",
            *(["Body"] * 9),
            "- ii -",
            *(["Body"] * 9),
            "- iii -",
            *(["Body"] * 9),
            "(PAGE)",
        ]
    )
    analysis = analyze_page_markers(text)
    assert [marker.page_number for marker in analysis.markers[:3]] == [1, 2, 3]
    assert analysis.markers[-1].kind == "boundary"
    assert analysis.markers[-1].page_number is None
    assert analysis.terminal_state.value == "none"


def test_ascii_numeric_table_burst_is_preserved() -> None:
    text = "Revenue  1  100\nRevenue  2  200\nRevenue  3  300\n"
    analysis = analyze_page_markers(text)
    assert analysis.markers == ()
    assert strip_page_markers(text, analysis) == text


def test_ascii_repeating_header_is_separate_from_page_labels() -> None:
    lines: list[str] = []
    for page in range(1, 4):
        lines.extend(["<PAGE>", str(page), "ACME CORPORATION"])
        lines.extend(["Body content for this page."] * 9)
    analysis = analyze_page_markers("\n".join(lines))
    assert any(marker.kind == "repeating_header" for marker in analysis.markers)
    assert any(
        decision.reason == "repeating_header_footer_template"
        for decision in analysis.decisions
    )


@pytest.mark.parametrize(
    ("kind", "labels"),
    [
        (PageMarkerKind.BARE_NUMBER, ("1", "2", "3")),
        (PageMarkerKind.ROMAN_NUMBER, ("i", "ii", "iii")),
        (PageMarkerKind.DASHED_NUMBER, ("— 1 —", "— 2 —", "— 3 —")),
        (PageMarkerKind.PIPE_NUMBER, ("| 1 |", "| 2 |", "| 3 |")),
        (PageMarkerKind.PAREN_NUMBER, ("( 1 )", "( 2 )", "( 3 )")),
        (PageMarkerKind.DOTTED_NUMBER, ("1.", "2.", "3.")),
        (PageMarkerKind.NUMBER_FIRST, ("1  Continued", "2  Continued", "3  Continued")),
        (
            PageMarkerKind.TRAILING_NUMBER,
            ("Continued  1", "Continued  2", "Continued  3"),
        ),
        (
            PageMarkerKind.INLINE_PAGE_NUMBER,
            ("Report Page 1", "Report Page 2", "Report Page 3"),
        ),
    ],
)
def test_anchorless_marker_families_are_promoted(
    kind: str, labels: tuple[str, str, str]
) -> None:
    lines: list[str] = []
    for label in labels:
        lines.append(label)
        lines.extend(["Narrative body content."] * 8)
    analysis = analyze_page_markers("\n".join(lines))
    assert [marker.kind for marker in analysis.markers] == [kind] * 3
    assert [marker.page_number for marker in analysis.markers] == [1, 2, 3]


def test_namespace_runs_stay_independent_and_multiline_occupancy_is_recorded() -> None:
    lines: list[str] = []
    for value in range(1, 4):
        lines.extend([str(value), *(["Body"] * 8)])
    for roman in ("i", "ii", "iii"):
        lines.extend([roman, *(["Body"] * 8)])
    text = "\n".join(lines)
    analysis = analyze_page_markers(text)
    assert {run.namespace for run in analysis.page_number_runs} == {"arabic", "roman"}
    multiline = analyze_page_markers("  <PAGE> 12  \nBody\n")
    marker = multiline.markers[0]
    assert marker.start_line == 0 and marker.end_line == 0
    assert 0 in multiline.occupied_lines


def test_html_repeated_visible_page_nodes_are_removed_by_dom_path() -> None:
    text = """<html><body>
<div class="page-number">1</div><p>First page prose.</p>
<div class="page-number">2</div><p>Second page prose.</p>
<div class="page-number">3</div><p>Third page prose.</p>
</body></html>"""
    soup = parse_html(text)
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert [marker.kind for marker in analysis.markers] == [
        PageMarkerKind.HTML_NODE
    ] * 3
    assert all(marker.coordinate_frame == "dom" for marker in analysis.markers)
    assert len(apply_html_page_decisions(soup, analysis)) == 3
    rendered = str(soup)
    assert "page-number" not in rendered
    assert "First page prose." in rendered


def test_html_hidden_and_avoid_page_values_are_preserved() -> None:
    text = """<html><body>
<div class="page-number" hidden>1</div>
<div style="page-break-before: avoid">2</div>
</body></html>"""
    soup = parse_html(text)
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert analysis.terminal_state.value == "no_visible_labels"
    assert not apply_html_page_decisions(soup, analysis)
    assert "1" in str(soup) and "2" in str(soup)


def test_html_actual_page_break_is_context_but_avoid_is_not() -> None:
    text = """<html><body>
<div style="page-break-before: always">1</div>
<div style="page-break-before: avoid">2</div>
</body></html>"""
    soup = parse_html(text)
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert [marker.page_number for marker in analysis.markers] == [1]
    assert len(apply_html_page_decisions(soup, analysis)) == 1
    assert "1" not in str(soup) and "2" in str(soup)


def test_html_page_footer_table_is_allowed_but_financial_table_is_not() -> None:
    footer = """<table class="page-footer"><tr><td>Page 1</td></tr></table>
<table class="page-footer"><tr><td>Page 2</td></tr></table>
<table class="page-footer"><tr><td>Page 3</td></tr></table>"""
    financial = """<table><tr><td>Revenue</td><td>100</td></tr>
<tr><td>Net income</td><td>20</td></tr></table>"""
    footer_soup = parse_html(f"<html><body>{footer}</body></html>")
    footer_analysis = enrich_html_analysis(
        analyze_page_markers(footer, representation="html"),
        footer_soup,
        source_text=footer,
    )
    assert {marker.kind for marker in footer_analysis.markers} == {
        PageMarkerKind.TABLE_FOOTER
    }
    financial_soup = parse_html(f"<html><body>{financial}</body></html>")
    financial_analysis = enrich_html_analysis(
        analyze_page_markers(financial, representation="html"),
        financial_soup,
        source_text=financial,
    )
    assert financial_analysis.markers == ()


def test_html_label_scan_keeps_generic_labels_with_hr_candidates() -> None:
    text = """<html><body>
    <p><hr><p>1</p><hr><p>2</p><hr><p>3</p>
    <p align="center">F-1</p><p align="center">F-2</p>
    <p align="center">F-3</p>
    </body></html>"""
    soup = BeautifulSoup(text, "lxml")
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert any(
        run.namespace == "F"
        and [candidate.value for candidate in run.candidates] == [1, 2, 3]
        for run in analysis.page_number_runs
    )


def test_ascii_slot_preserves_unique_prose_but_keeps_repeated_prose_header() -> None:
    unique = [
        (
            1,
            "During 1999 the Company entered into a new arrangement for investors",
            "a",
        ),
        (2, "During 2000 the Company entered into a new arrangement for holders", "b"),
        (3, "During 2001 the Company entered into a new arrangement for lenders", "c"),
        (
            4,
            "During 2002 the Company entered into a new arrangement for customers",
            "d",
        ),
    ]
    assert _slot_heading_members(unique) == []

    repeated = [(index, unique[0][1], "same") for index in range(1, 5)]
    assert _slot_heading_members(repeated) == repeated


def _footer_tables(values: int | list[int], cell_middle: str = "Page") -> str:
    numbers = [values] if isinstance(values, int) else values
    return "".join(
        f'<table style="border-collapse: collapse; width: 100%">'
        f"<tr><td>ACME 10-K</td><td>{cell_middle}</td>"
        f'<td style="text-align: center">{number}</td>'
        f"<td>ACME Corp</td></tr></table>"
        for number in numbers
    )


def test_html_word_style_table_footer_family_is_detected() -> None:
    text = f"<html><body>{_footer_tables([1, 2, 3, 4])}<p>Body prose.</p></body></html>"
    soup = parse_html(text)
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert any(
        run.namespace == "arabic"
        and [candidate.value for candidate in run.candidates] == [1, 2, 3, 4]
        for run in analysis.page_number_runs
    )
    assert {marker.kind for marker in analysis.markers} == {PageMarkerKind.TABLE_FOOTER}


@pytest.mark.parametrize(
    "middle",
    [
        "$1,234",  # currency + thousands separator
        "45%",  # percent
        "1,234.56",  # thousands + decimal
        "(1,234)",  # parenthesized number
        "December 31, 2024",  # SEC date
    ],
)
def test_html_financial_footer_tables_are_rejected(middle: str) -> None:
    text = f"<html><body>{_footer_tables([1, 2, 3], cell_middle=middle)}</body></html>"
    soup = parse_html(text)
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert analysis.markers == ()
    assert analysis.page_number_runs == ()


def test_html_multiyear_footer_table_is_rejected() -> None:
    rows = "".join(
        f'<table style="border-collapse: collapse; width: 100%">'
        f"<tr><td>Fiscal {year} results</td>"
        f'<td style="text-align: center">{number}</td>'
        f"<td>ACME Corp</td></tr></table>"
        for year, number in ((2023, 1), (2024, 2), (2025, 3))
    )
    text = f"<html><body>{rows}</body></html>"
    soup = parse_html(text)
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert analysis.markers == ()
    assert analysis.page_number_runs == ()


def test_html_footnote_prose_table_is_rejected_by_stop_words() -> None:
    # d699820d10k-style false positive: bare footnote numbers next to short
    # prose. Two distinct page-guard stop words must reject it even though the
    # sequence (3, 5, 6) is monotone and no financial tokens are present.
    rows = "".join(
        f"<table><tr><td>{number}</td>"
        f"<td>The reported total was above the plan for this period.</td></tr></table>"
        for number in (3, 5, 6)
    )
    text = f"<html><body>{rows}</body></html>"
    soup = parse_html(text)
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert analysis.markers == ()
    assert analysis.page_number_runs == ()


def test_html_oversized_prose_cell_is_rejected() -> None:
    filler = "word " * 60
    rows = "".join(
        f"<table><tr><td>{number}</td><td>{filler}</td></tr></table>"
        for number in (1, 2, 3)
    )
    text = f"<html><body>{rows}</body></html>"
    soup = parse_html(text)
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert analysis.markers == ()
    assert analysis.page_number_runs == ()


def test_html_oversized_cell_count_is_rejected() -> None:
    rows = "".join(
        "<table><tr>"
        + "".join(f"<td>{index}</td>" for index in range(10))
        + "</tr></table>"
        for _ in range(3)
    )
    text = f"<html><body>{rows}</body></html>"
    soup = parse_html(text)
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert analysis.markers == ()
    assert analysis.page_number_runs == ()


def test_html_no_page_label_evidence_skips_generic_scan() -> None:
    # bwc-style document: financial tables full of bare digits, no strong
    # labels, no HR. The generic div/span/font scan must not run, but the
    # financial tables must also not be promoted to footer families.
    text = (
        "<html><body>"
        "<table><tr><td>Revenue</td><td>$1,234.56</td><td>45%</td></tr></table>"
        "<table><tr><td>Net income</td><td>2,000</td><td>10%</td></tr></table>"
        "<table><tr><td>Year</td><td>2023</td><td>2024</td></tr></table>"
        "<p>Total assets grew 12.5% year over year with 3,456 units.</p>"
        "</body></html>"
    )
    soup = parse_html(text)
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert analysis.markers == ()
    assert analysis.page_number_runs == ()
    assert analysis.terminal_state.value == "no_visible_labels"


def test_html_signature_mismatched_recovery_stays_inferred() -> None:
    # F-4 sits in an <h6>: structurally different from the confirmed p-footer
    # family. Stripping it would be a false removal (it may be a heading), so
    # it must remain inferred-only metadata and survive text conversion.
    text = (
        "<html><body>"
        "<p align='center'>F-1</p><p>Body one.</p>"
        "<p align='center'>F-2</p><p>Body two.</p>"
        "<p align='center'>F-3</p><p>Body three.</p>"
        "<h6>F-4</h6><p>Body four.</p>"
        "<p align='center'>F-5</p><p>Body five.</p>"
        "</body></html>"
    )
    soup = parse_html(text)
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert any(
        run.namespace == "F"
        and sorted(candidate.value for candidate in run.candidates) == [1, 2, 3, 5]
        for run in analysis.page_number_runs
    )
    assert not [marker for marker in analysis.markers if marker.text == "F-4"]
    assert any(
        boundary.page_number == 4 and boundary.namespace == "F"
        for boundary in analysis.inferred_boundaries
    )
    apply_html_page_decisions(soup, analysis)
    rendered = str(soup)
    assert "F-4" in rendered
    assert "Body four." in rendered


def test_html_recovery_maps_same_signature_label_to_strippable_node() -> None:
    # F-4 is hidden from the generic scan inside a styled wrapper but keeps
    # the exact footer shape (p align=center) and sibling context, so the
    # recovery must promote it to a real strippable marker.
    text = (
        "<html><body>"
        "<p align='center'>F-1</p><p>Body one.</p>"
        "<p align='center'>F-2</p><p>Body two.</p>"
        "<p align='center'>F-3</p><p>Body three.</p>"
        "<div style='display:block'><p align='center'>F-4</p></div>"
        "<p>Body four.</p>"
        "<p align='center'>F-5</p><p>Body five.</p>"
        "</body></html>"
    )
    soup = parse_html(text)
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert any(
        run.namespace == "F"
        and sorted(candidate.value for candidate in run.candidates) == [1, 2, 3, 4, 5]
        for run in analysis.page_number_runs
    )
    assert [marker.text for marker in analysis.markers if marker.text == "F-4"]
    assert not [
        boundary
        for boundary in analysis.inferred_boundaries
        if boundary.page_number == 4 and boundary.namespace == "F"
    ]
    apply_html_page_decisions(soup, analysis)
    rendered = str(soup)
    assert "F-4" not in rendered
    assert "Body four." in rendered


def test_html_hidden_labels_stay_inferred_not_recovered() -> None:
    parts = ["<html><body>"]
    for value in range(1, 5):
        parts.append(f'<p align="center">F-{value}</p><p>Body {value}.</p>')
    for value in range(5, 9):  # hidden -> not validated as visible candidates
        parts.append(f'<span style="display:none">F-{value}</span><p>Body {value}.</p>')
    for value in (9, 10):
        parts.append(f'<p align="center">F-{value}</p><p>Body {value}.</p>')
    parts.append("</body></html>")
    text = "".join(parts)
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        parse_html(text),
        source_text=text,
    )
    assert any(
        run.namespace == "F"
        and [candidate.value for candidate in run.candidates] == [1, 2, 3, 4, 9, 10]
        for run in analysis.page_number_runs
    )
    inferred = sorted(
        boundary.page_number
        for boundary in analysis.inferred_boundaries
        if boundary.namespace == "F" and boundary.reason == "bounded_literal_recovery"
    )
    assert inferred == [5, 6, 7, 8]


def test_html_regions_report_uncovered_intervals() -> None:
    text = (
        "<html><body>"
        "<p>Refer to Page 1 and Page 2 for details.</p>"
        "<p>Page 3 continues the introduction.</p>"
        "<p>Body prose without any page furniture.</p>"
        "<p align='center'>A-1</p><p>Section text one.</p>"
        "<p align='center'>A-2</p><p>Section text two.</p>"
        "<p align='center'>A-3</p><p>Section text three.</p>"
        "</body></html>"
    )
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        parse_html(text),
        source_text=text,
    )
    statuses = {region.status for region in analysis.regions}
    assert "referential_labels" in statuses
    assert "likely_pageless" in statuses


def test_html_regions_report_weak_numeric_without_families() -> None:
    text = (
        "<html><body>"
        "<table><tr><td>Revenue</td><td>$1,234.56</td><td>45%</td></tr></table>"
        "<table><tr><td>Year</td><td>2003</td></tr>"
        "<tr><td>Amount</td><td>2004</td></tr>"
        "<tr><td>Count</td><td>2005</td></tr></table>"
        "<p>Total assets grew 12.5% year over year with 3,456 units.</p>"
        "</body></html>"
    )
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        parse_html(text),
        source_text=text,
    )
    assert analysis.markers == ()
    assert any(region.status == "weak_numeric" for region in analysis.regions)
    assert html_has_page_label_evidence("<p>F-3</p>")


def test_html_has_page_label_evidence_gate() -> None:
    assert html_has_page_label_evidence("<p>F-3</p>")
    assert html_has_page_label_evidence("<td>page 4</td>")
    assert html_has_page_label_evidence("<hr><p>1</p>")
    assert html_has_page_label_evidence("<table><tr><td>7</td></tr></table>")
    assert not html_has_page_label_evidence("<p>Plain prose without numbers.</p>")
    assert not html_has_page_label_evidence("")


def _make_run(values_and_lines: list[tuple[int, int]]) -> object:
    candidates = tuple(
        PageCandidate(
            0,
            0,
            line,
            line,
            str(value),
            "bare_number",
            "arabic",
            value,
        )
        for value, line in values_and_lines
    )
    return pm_mod.PageNumberRun(
        "bare_number",
        "arabic",
        candidates,
        1.0,
        0.0,
        0.0,
        1.0,
        -1,
        -1,
        "anchorless",
    )


def test_heal_run_repairs_inversion_spikes_and_duplicates() -> None:
    # d-50408 signature: foreign table total 86 between 23 and a duplicate 20.
    run = _make_run(
        [(value, 100 + index * 10) for index, value in enumerate(range(2, 24))]
        + [(86, 330), (20, 340)]
        + [(value, 350 + index * 10) for index, value in enumerate(range(24, 47))]
    )
    healed, inferred, promoted = heal_run(run, run.candidates)
    values = [candidate.value for candidate in healed.candidates]
    assert 86 not in values
    assert values == sorted(set(values))
    assert inferred == ()
    assert promoted == ()


def test_heal_run_suppresses_values_observed_by_stronger_runs() -> None:
    run = _make_run([(20, 100), (86, 200), (20, 300), (24, 400)])
    _healed, inferred, _ = heal_run(
        run,
        run.candidates,
        stronger_values=frozenset(range(21, 47)),
    )
    inferred_values = {boundary.page_number for boundary in inferred}
    assert inferred_values.isdisjoint(range(21, 47))


def test_heal_run_requires_page_break_evidence_for_gaps() -> None:
    run = _make_run([(17, 100), (25, 900)])
    without_evidence = heal_run(run, run.candidates, page_break_lines=frozenset())
    assert without_evidence[1] == ()
    breaks = frozenset(range(150, 880, 90))
    with_evidence = heal_run(run, run.candidates, page_break_lines=breaks)
    assert [boundary.page_number for boundary in with_evidence[1]] == list(
        range(18, 25)
    )
    assert {boundary.reason for boundary in with_evidence[1]} <= {
        "validated_page_break_count",
        "page_break_supported",
    }


def test_heal_run_promotes_compatible_anchorless_candidates() -> None:
    run = _make_run([(1, 100), (2, 200), (3, 300), (5, 500), (6, 600)])
    anchorless = [
        PageCandidate(0, 0, 400, 400, "4", "bare_number", "arabic", 4),
        PageCandidate(0, 0, 250, 250, "86", "bare_number", "arabic", 86),
    ]
    healed, inferred, promoted = heal_run(run, anchorless)
    values = [candidate.value for candidate in healed.candidates]
    assert 4 in values
    assert 86 not in values
    assert inferred == ()
    assert len(promoted) == 1


def test_text_cleanup_does_not_reuse_stale_coordinate_frame() -> None:
    original = "Page 1\nBody\n"
    changed = "Prefix\nPage 1\nBody\n"
    analysis = analyze_page_markers(original)
    assert strip_page_markers(changed, analysis) == "Prefix\nBody\n"


def test_letter_number_monotonic_f_sequence_accepted_by_default() -> None:
    text = "\n".join(f"F-{i}" for i in range(1, 6))
    analysis = analyze_page_markers(text)
    assert [marker.page_number for marker in analysis.markers] == [1, 2, 3, 4, 5]
    assert all(
        marker.kind == PageMarkerKind.LETTER_NUMBER for marker in analysis.markers
    )
    assert all(d.action == PageMarkerAction.REMOVE for d in analysis.decisions)


def test_letter_number_non_monotone_sequence_preserved() -> None:
    text = "F-1\nF-3\nF-2\n"
    analysis = analyze_page_markers(text)
    assert len(analysis.markers) == 3
    assert all(m.kind == PageMarkerKind.LETTER_NUMBER for m in analysis.markers)
    assert all(d.action == PageMarkerAction.PRESERVE for d in analysis.decisions)


def test_ordinary_sec_form_references_not_removed() -> None:
    text = "Form S-1\nForm F-3\nSome content.\n"
    analysis = analyze_page_markers(text)
    assert not any(m.kind == PageMarkerKind.LETTER_NUMBER for m in analysis.markers)
    assert strip_page_markers(text, analysis) == text


def _recipe_sample(signature_comment: str, value: int) -> str:
    return (
        f"<!-- {signature_comment} --><html><body>"
        "<p align='center'>Intro page.</p>"
        + "".join(
            f"<p align='center'>F-{n}</p><p>Body {n} content.</p>"
            for n in range(1, value + 1)
        )
        + "</body></html>"
    )


def test_html_recipe_cache_learns_and_reuses_signature_profile() -> None:
    import defs.sec_forms.page_markers.html.probes as html_mod

    html_mod._RECIPE_CACHE.clear()
    html_mod._RECIPE_REJECTED.clear()
    first = _recipe_sample("Document created using Wdesk 1", 6)
    first_tree = parse_html(first)
    first_analysis = enrich_html_analysis(
        analyze_page_markers(first, representation="html"),
        first_tree,
        source_text=first,
    )
    assert len(first_analysis.markers) >= 3
    signature = html_mod._html_recipe_signature(first)
    assert "wdesk" in signature
    assert signature in html_mod._RECIPE_CACHE

    second = _recipe_sample("Document created using Wdesk 1", 9)
    second_tree = parse_html(second)
    second_analysis = enrich_html_analysis(
        analyze_page_markers(second, representation="html"),
        second_tree,
        source_text=second,
    )
    values = {
        marker.page_number for marker in second_analysis.markers if marker.page_number
    }
    assert values == {1, 2, 3, 4, 5, 6, 7, 8, 9}
    html_mod._RECIPE_CACHE.clear()
    html_mod._RECIPE_REJECTED.clear()


def test_html_recipe_cache_rejects_mismatched_profile_and_falls_back() -> None:
    import defs.sec_forms.page_markers.html.probes as html_mod

    html_mod._RECIPE_CACHE.clear()
    html_mod._RECIPE_REJECTED.clear()
    layout_a = (
        "<!-- PAGEBREAK --><html><body>"
        + "".join(
            f"<p align='center'>F-{n}</p><p>Body {n}.</p>" for n in range(1, 6)
        )
        + "</body></html>"
    )
    layout_a_tree = parse_html(layout_a)
    enrich_html_analysis(
        analyze_page_markers(layout_a, representation="html"),
        layout_a_tree,
        source_text=layout_a,
    )
    # Same platform signature but a different label shape; the learned
    # profile must be rejected (memoized as such) and the full scan must
    # still produce the complete marker set.
    layout_b = (
        "<!-- PAGEBREAK --><html><body>"
        + "".join(
            f"<div style='width:100%'><span>P-{n}</span>"
            f"<p>Content {n}.</p></div>"
            for n in range(1, 6)
        )
        + "</body></html>"
    )
    layout_b_tree = parse_html(layout_b)
    analysis = enrich_html_analysis(
        analyze_page_markers(layout_b, representation="html"),
        layout_b_tree,
        source_text=layout_b,
    )
    values = {
        marker.page_number for marker in analysis.markers if marker.page_number
    }
    assert values == {1, 2, 3, 4, 5}
    assert html_mod._RECIPE_REJECTED
    html_mod._RECIPE_CACHE.clear()
    html_mod._RECIPE_REJECTED.clear()


def test_recipe_platform_vocabulary_compiles_from_constants() -> None:
    from defs.sec_forms.page_markers.constants import _RECIPE_PLATFORM_RE

    assert _RECIPE_PLATFORM_RE.search("Document created using Wdesk 1")
    assert _RECIPE_PLATFORM_RE.search("PAGEBREAK")
    assert _RECIPE_PLATFORM_RE.search("Field: Rule-Page")
    assert not _RECIPE_PLATFORM_RE.search("random prose comment")
