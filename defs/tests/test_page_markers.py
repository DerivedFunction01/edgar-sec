"""Contract and unit tests for shared page-marker analysis."""

from __future__ import annotations

import importlib

import pytest
from bs4 import BeautifulSoup

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
    soup = BeautifulSoup(text, "lxml")
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert [marker.kind for marker in analysis.markers] == [
        PageMarkerKind.HTML_NODE
    ] * 3
    assert all(marker.coordinate_frame == "dom" for marker in analysis.markers)
    assert apply_html_page_decisions(soup, analysis) == 3
    rendered = str(soup)
    assert "page-number" not in rendered
    assert "First page prose." in rendered


def test_html_hidden_and_avoid_page_values_are_preserved() -> None:
    text = """<html><body>
<div class="page-number" hidden>1</div>
<div style="page-break-before: avoid">2</div>
</body></html>"""
    soup = BeautifulSoup(text, "lxml")
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert analysis.terminal_state.value == "no_visible_labels"
    assert apply_html_page_decisions(soup, analysis) == 0
    assert "1" in str(soup) and "2" in str(soup)


def test_html_actual_page_break_is_context_but_avoid_is_not() -> None:
    text = """<html><body>
<div style="page-break-before: always">1</div>
<div style="page-break-before: avoid">2</div>
</body></html>"""
    soup = BeautifulSoup(text, "lxml")
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert [marker.page_number for marker in analysis.markers] == [1]
    assert apply_html_page_decisions(soup, analysis) == 1
    assert "1" not in str(soup) and "2" in str(soup)


def test_html_page_footer_table_is_allowed_but_financial_table_is_not() -> None:
    footer = """<table class="page-footer"><tr><td>Page 1</td></tr></table>
<table class="page-footer"><tr><td>Page 2</td></tr></table>
<table class="page-footer"><tr><td>Page 3</td></tr></table>"""
    financial = """<table><tr><td>Revenue</td><td>100</td></tr>
<tr><td>Net income</td><td>20</td></tr></table>"""
    footer_soup = BeautifulSoup(f"<html><body>{footer}</body></html>", "lxml")
    footer_analysis = enrich_html_analysis(
        analyze_page_markers(footer, representation="html"),
        footer_soup,
        source_text=footer,
    )
    assert {marker.kind for marker in footer_analysis.markers} == {
        PageMarkerKind.TABLE_FOOTER
    }
    financial_soup = BeautifulSoup(f"<html><body>{financial}</body></html>", "lxml")
    financial_analysis = enrich_html_analysis(
        analyze_page_markers(financial, representation="html"),
        financial_soup,
        source_text=financial,
    )
    assert financial_analysis.markers == ()


def test_text_cleanup_does_not_reuse_stale_coordinate_frame() -> None:
    original = "Page 1\nBody\n"
    changed = "Prefix\nPage 1\nBody\n"
    analysis = analyze_page_markers(original)
    assert strip_page_markers(changed, analysis) == "Prefix\nBody\n"
