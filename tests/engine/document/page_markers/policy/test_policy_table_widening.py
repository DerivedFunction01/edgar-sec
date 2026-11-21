"""When a removal widens to a whole table, and when it must not."""

from __future__ import annotations

from edgar_sec.engine.document.page_markers.detector import analyze_page_markers
from edgar_sec.engine.document.page_markers.models import (
    PageMarker,
    PageMarkerAction,
    PageMarkerAnalysis,
    PageMarkerDecision,
    PageMarkerKind,
)
from edgar_sec.engine.document.page_markers.policy import apply_page_markers
from tests.engine.document.page_markers.policy.policy_support import _paged


def _block_analysis(
    text: str, first_line: int, last_line: int, kind: str
) -> PageMarkerAnalysis:
    # One REMOVE decision whose marker covers whole lines first..last exactly.
    lines = text.split("\n")
    start = sum(len(line) + 1 for line in lines[:first_line])
    end = start + sum(len(line) + 1 for line in lines[first_line:last_line])
    end += len(lines[last_line])
    marker = PageMarker(
        start=start,
        end=end,
        text=text[start:end],
        kind=kind,
        start_line=first_line,
        end_line=last_line,
    )
    decision = PageMarkerDecision(
        marker=marker, action=PageMarkerAction.REMOVE, reason="test"
    )
    return PageMarkerAnalysis(
        markers=(marker,),
        decisions=(decision,),
        page_boundaries=(),
        source_text=text,
    )


def _spanning_label_table(segments: list[list[str]]) -> str:
    lines = ["Intro", "<TABLE>"]
    for index, segment in enumerate(segments):
        if index:
            lines.append("<PAGE>")
        lines.extend(segment)
    lines.extend(["</TABLE>", "Outro"])
    return "\n".join(lines) + "\n"


def test_a_removal_overlapping_a_compact_table_widens_to_the_whole_table() -> None:
    text = _paged(4, header="ABC CORP")
    result, _artifacts, _templates, _next_id = apply_page_markers(text)
    assert "<TABLE>" not in result
    assert result.count("</TABLE>") == result.count("<TABLE>")


def test_a_compact_table_with_undecided_content_is_not_widened_into() -> None:
    # Only the page-of-total line carries a decision; the data lines beside
    # it are content, so the removal stays on the marker's own line.
    text = (
        "Intro\n"
        "<TABLE>\n"
        "Category A          100\n"
        "Page 1 of 2\n"
        "Category B          200\n"
        "</TABLE>\n"
        "Outro\n"
    )
    result, _artifacts, _templates, _next_id = apply_page_markers(text)
    assert "Category A          100" in result
    assert "Category B          200" in result
    assert "<TABLE>" in result
    assert "Page 1 of 2" not in result


def test_a_block_range_overlapping_a_table_is_unioned_not_replaced() -> None:
    # M1 reproduction (defect_2 census): the block decision starts before a
    # fully-decided compact table; replacing its range with the table's kept
    # the block's head line as silent under-removal — the sub='none' orphan
    # shape of the "Division of Corporation Finance" letterheads
    # (0000829224-21-000090). Union removes the head and the table together.
    text = (
        "Division of Corporation Finance\n"
        "<TABLE>\n"
        "ACME CORP\n"
        "</TABLE>\n"
        "Body text survives.\n"
    )
    analysis = _block_analysis(text, 0, 2, PageMarkerKind.REPEATING_FOOTER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "Division of Corporation Finance" not in result
    assert "<TABLE>" not in result
    assert "Body text survives." in result


def test_a_marker_inside_a_compact_table_still_widens_to_the_whole_table() -> None:
    # Union semantics keep the atomic-table behaviour: a lone decided banner
    # line still takes the wrapper tags with it.
    text = "Intro\n<TABLE>\nACME CORP\n</TABLE>\nOutro\n"
    analysis = _block_analysis(text, 2, 2, PageMarkerKind.REPEATING_HEADER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" not in result
    assert "ACME CORP" not in result
    assert "Outro" in result


def test_a_fee_table_is_not_widened_into() -> None:
    # Specimen 0000080248-06-000005 (defect_4 D4-B): every fee line is
    # data-shaped (a bare percent), so the compact table is not furniture
    # however fully a block decision covers its lines.
    text = (
        "Intro\n"
        "<TABLE>\n"
        "Maximum sales load imposed on purchases (%)       None\n"
        "Maximum contingent deferred sales charge (%)      None\n"
        "Redemption Fees (%)                           None (1)\n"
        "</TABLE>\n"
        "Outro\n"
    )
    analysis = _block_analysis(text, 2, 4, PageMarkerKind.REPEATING_FOOTER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert "</TABLE>" in result
    assert "Outro" in result


def test_a_proxy_header_table_is_not_widened_into() -> None:
    # Specimen 0001213900-20-023787 (defect_4 D4-B): the meeting/record lines
    # carry guttered figures, so the header table is not widened over.
    text = (
        "Intro\n"
        "<TABLE>\n"
        "Ticker:          MMM         Security ID:   88579Y101\n"
        "Meeting Date:  MAY 12, 2020  Meeting Type:  Annual\n"
        "Record Date:   MAR 17, 2020\n"
        "</TABLE>\n"
        "Outro\n"
    )
    analysis = _block_analysis(text, 2, 4, PageMarkerKind.REPEATING_FOOTER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert "</TABLE>" in result


def test_a_rider_table_is_not_widened_into() -> None:
    # Specimen 0001072613-20-000194 (defect_4 D4-B): the rider row is a
    # guttered date/identifier row, so its table is not widened over.
    text = (
        "Intro\n"
        "<TABLE>\n"
        "Rider Effective Date     Bond Holder       Bond Number      Rider\n"
        "     11/4/2019        Barings BDC, Inc.  64-MGU-19-A48107     1\n"
        "</TABLE>\n"
        "Outro\n"
    )
    analysis = _block_analysis(text, 2, 3, PageMarkerKind.REPEATING_FOOTER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert "</TABLE>" in result


def test_a_date_table_is_not_widened_into() -> None:
    # A one-line date table (residual_other R-E shape) is a data table: its
    # only content line is a full date, so coverage alone cannot widen.
    text = "Intro\n<TABLE>\nAugust 31, 2020 (unaudited)\n</TABLE>\nOutro\n"
    analysis = _block_analysis(text, 2, 2, PageMarkerKind.REPEATING_HEADER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert "</TABLE>" in result


def test_a_year_header_table_is_not_widened_into() -> None:
    # Specimen shape 0001205613-04-000173 (residual_numeric R5): a year pair
    # is a column header, content by position, invisible to prose tests.
    text = "Intro\n<TABLE>\n2004 / 2003\n</TABLE>\nOutro\n"
    analysis = _block_analysis(text, 2, 2, PageMarkerKind.REPEATING_HEADER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert "</TABLE>" in result


def test_a_rule_lined_table_is_not_widened_into() -> None:
    # Specimen 0001539497-21-001637: rule lines are table borders, not
    # decided content lines, so they cannot satisfy full coverage.
    text = (
        "Intro\n"
        "<TABLE>\n"
        "-------------  --------------\n"
        "Annex A-1 ID#  Mortgage Loans\n"
        "-------------  --------------\n"
        "</TABLE>\n"
        "Outro\n"
    )
    analysis = _block_analysis(text, 2, 4, PageMarkerKind.REPEATING_FOOTER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert "</TABLE>" in result


def test_a_page_label_table_still_widens() -> None:
    # Furniture control for the data/date screens: a page-of-total line is
    # neither data-shaped nor a date line, so its table still widens whole.
    text = "Intro\n<TABLE>\nPage 1 of 2\n</TABLE>\nOutro\n"
    analysis = _block_analysis(text, 2, 2, PageMarkerKind.PAGE_NUMBER_OF_TOTAL)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" not in result
    assert "Page 1 of 2" not in result
    assert "Outro" in result


def test_labels_inside_a_page_spanning_table_are_removed_with_the_table() -> None:
    # E5 shape: one table element spanning several pages, every appendix
    # label inside it; the whole furniture table widens away as one block.
    text = _spanning_label_table(
        [["------", "A - 1"], ["------", "A - 2"], ["------", "A - 3"]]
    )
    analysis = analyze_page_markers(text, {"allow_table_furniture": True})
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" not in result
    assert "------" not in result
    assert "A - 1" not in result
    assert "A - 3" not in result
    assert "Intro" in result
    assert "Outro" in result


def test_labels_in_non_spanning_tables_are_not_newly_widened() -> None:
    # Control (the S-4 specimen shape): each label in its own compact table
    # is removed alone, exactly as before; its husk is not the spanning case.
    text = (
        "Intro\n"
        "<TABLE>\n------\nA - 1\n</TABLE>\n<PAGE>\nBody 1\n"
        "<TABLE>\n------\nA - 2\n</TABLE>\n<PAGE>\nBody 2\n"
        "<TABLE>\n------\nA - 3\n</TABLE>\n<PAGE>\nBody 3\n"
    )
    analysis = analyze_page_markers(text, {"allow_table_furniture": True})
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "A - 1" not in result
    assert result.count("<TABLE>") == 3
    assert result.count("------") == 3
    assert "Body 2" in result


def test_a_spanning_table_with_content_lines_is_not_widened() -> None:
    # A spanning table carrying undecided body rows is content: its labels
    # are removed alone and the table survives whole.
    text = _spanning_label_table(
        [
            ["------", "A - 1", "The merger agreement clause one applies."],
            ["------", "A - 2", "The merger agreement clause two applies."],
            ["------", "A - 3", "The merger agreement clause three applies."],
        ]
    )
    analysis = analyze_page_markers(text, {"allow_table_furniture": True})
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert "A - 1" not in result
    assert "clause two applies" in result


def test_a_spanning_table_without_a_letter_label_is_not_widened() -> None:
    # The spanning admission is scoped to appendix letter labels: bare page
    # numbers spanning a table keep the line-at-a-time behaviour.
    text = _spanning_label_table([["------", "1"], ["------", "2"], ["------", "3"]])
    analysis = analyze_page_markers(text, {"allow_table_furniture": True})
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert result.count("------") == 3
