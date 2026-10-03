"""Contract tests for TOC span detection."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.toc.finder import find_toc_span


def test_heading_and_dot_leader_rows_return_toc_span() -> None:
    text = """\
TABLE OF CONTENTS
PART I ........................................ 1
ITEM 1. BUSINESS ............................. 1
ITEM 1A. RISK FACTORS ......................... 8
PART I
ITEM 1. BUSINESS
"""
    toc = find_toc_span(text)
    assert toc is not None
    assert toc.method == "heading_rows"
    assert text.splitlines()[toc.start_line] == "TABLE OF CONTENTS"
    assert toc.end_line == 4
    assert text.splitlines()[toc.end_line] == "PART I"


def test_index_requires_toc_rows() -> None:
    assert find_toc_span("INDEX\nThe index is discussed below.\n") is None
    toc = find_toc_span(
        "INDEX\nITEM 1. BUSINESS ..................... 1\n"
        "ITEM 2. PROPERTIES ................... 4\n"
    )
    assert toc is not None
    assert toc.method == "weak_heading_rows"


def test_untagged_rows_can_define_approximate_toc() -> None:
    toc = find_toc_span(
        "PART I ........................................ 1\n"
        "ITEM 1. BUSINESS ............................. 1\n"
    )
    assert toc is not None
    assert toc.method == "aligned_rows"
    assert toc.approximate is True


def test_heading_without_rows_is_not_toc() -> None:
    assert find_toc_span("TABLE OF CONTENTS\nPART I\n") is None


def test_heading_toc_inside_table_ends_at_table_close() -> None:
    """Non-row lines and the ``</TABLE>`` tag stay inside the span instead of ending
    it at the first non-row line.
    """
    text = """\
TABLE OF CONTENTS
<TABLE>
PART I ........................................ 1
ITEM 1. BUSINESS ............................. 4
Document Incorporated by Reference
</TABLE>

PART I
ITEM 1. BUSINESS
"""
    toc = find_toc_span(text)
    assert toc is not None
    assert toc.method == "heading_rows"
    lines = text.splitlines()
    assert lines[toc.end_line] == "PART I"
    assert "</TABLE>" in "\n".join(lines[: toc.end_line])
    names = {evidence.name for evidence in toc.evidence}
    assert "toc_table_boundary" in names
    boundary = next(e for e in toc.evidence if e.name == "toc_table_boundary")
    assert "merged" not in boundary.details


def test_heading_toc_claims_split_continuation_table() -> None:
    """Non-row trailing lines stop the row scan before the close; the span still
    claims that close and merges the continuation table across the page break.
    """
    text = """\
TABLE OF CONTENTS
<TABLE>
PART I ........................................ 1
ITEM 1. BUSINESS ............................. 4
Document Incorporated by Reference
Incorporated documents are available upon request.
Requests should be directed to the registrant.
The registrant maintains copies at its principal office.
Copies are provided without charge to shareholders.
</TABLE>
<PAGE>

<TABLE>
ITEM 1A. RISK FACTORS ......................... 9
ITEM 2. PROPERTIES ........................... 14
</TABLE>

PART I
ITEM 1. BUSINESS
"""
    toc = find_toc_span(text)
    assert toc is not None
    assert toc.method == "heading_rows"
    lines = text.splitlines()
    assert toc.end_line == 17
    assert lines[toc.end_line] == "PART I"
    assert toc.end_line > 15
    names = {evidence.name for evidence in toc.evidence}
    assert "toc_table_boundary" in names
    boundary = next(e for e in toc.evidence if e.name == "toc_table_boundary")
    assert "merged across page break" in boundary.details


def test_tagged_html_toc_merges_aligned_subsection_rows() -> None:
    """Whitespace-column HTML TOCs merge a one-row continuation table."""
    text = """\
<TABLE>
Item 1 - Business                                      1
Overview                                               1
Markets and Customers                                  3
Item 2 - Properties                                   10
</TABLE>

<TABLE>
Item 15 - Exhibits, Financial Statement Schedules     36
</TABLE>

As used herein, the Company means the registrant.
"""
    toc = find_toc_span(text)

    assert toc is not None
    assert toc.method == "tagged_table_merged"
    assert text.splitlines()[toc.end_line].startswith("As used herein")


def test_unclosed_table_before_heading_does_not_claim() -> None:
    """An unbalanced open table that never closes within the window is not claimed."""
    text = """\
<TABLE>
TABLE OF CONTENTS
PART I ........................................ 1
ITEM 1. BUSINESS ............................. 4
PART I
ITEM 1. BUSINESS
The company operates worldwide.
"""
    toc = find_toc_span(text)
    assert toc is not None
    names = {evidence.name for evidence in toc.evidence}
    assert "toc_table_boundary" not in names
    assert toc.end_line == 4


def test_offsets_point_at_the_claimed_lines() -> None:
    text = (
        "cover\nTABLE OF CONTENTS\nPART I ....... 1\nITEM 1. BUSINESS ....... 1\nbody\n"
    )
    toc = find_toc_span(text)

    assert toc is not None
    lines = text.splitlines(keepends=True)
    assert toc.start_offset == sum(len(line) for line in lines[: toc.start_line])
    assert toc.end_offset == sum(len(line) for line in lines[: toc.end_line])


def test_a_heading_whose_rows_start_far_later_is_not_a_toc_start() -> None:
    text = (
        "TABLE OF CONTENTS\n"
        + "filler line\n" * 20
        + "PART I ....... 1\nITEM 1. BUSINESS ....... 1\n"
    )
    toc = find_toc_span(text)

    assert toc is not None
    assert toc.method == "aligned_rows"
    assert toc.approximate is True


def test_start_line_is_respected() -> None:
    text = "PART I ....... 1\nITEM 1. BUSINESS ....... 1\n"

    assert find_toc_span(text, start_line=1) is None
    assert find_toc_span(text, start_line=0) is not None


def test_max_lines_bounds_the_scan() -> None:
    text = "PART I ....... 1\nITEM 1. BUSINESS ....... 1\n"

    assert find_toc_span(text, max_lines=1) is None


def test_minimum_rows_gates_a_single_row() -> None:
    assert find_toc_span("TABLE OF CONTENTS\nPART I ....... 1\n") is None
    assert (
        find_toc_span("TABLE OF CONTENTS\nPART I ....... 1\n", minimum_rows=1)
        is not None
    )


def test_empty_documents_return_none() -> None:
    assert find_toc_span("") is None
    assert find_toc_span("\n\n\n") is None


def test_a_row_sequence_reset_trims_the_span() -> None:
    text = (
        "TABLE OF CONTENTS\n"
        "Item 1. Business ..... 1\nItem 2 ..... 2\n"
        "Item 1A ..... 3\n"
        "body prose follows the table of contents here\n"
    )
    toc = find_toc_span(text)

    assert toc is not None
    names = {evidence.name for evidence in toc.evidence}
    assert "toc_sequence_reset" in names
    assert toc.end_line == 3
