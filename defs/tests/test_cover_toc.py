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
