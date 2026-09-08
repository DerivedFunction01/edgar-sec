from __future__ import annotations

from defs.sec_forms.cover import find_toc_span


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
    """A heading TOC whose rows sit in a TABLE claims the table's close.

    Rows that do not parse as TOC rows and the ``</TABLE>`` tag itself stay
    inside the span instead of ending at the first non-row line.
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
    """A page-break-split continuation table is claimed through its close.

    Non-row trailing lines inside the first table stop the row scan before
    its close; the span still claims that close and merges the continuation
    table across the page break.
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
