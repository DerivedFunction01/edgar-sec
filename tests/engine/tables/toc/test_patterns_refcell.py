"""Pins for the reference forms homed from the ref-cell/header sites.
Each case reproduces the accepted/rejected shapes the originating site
relied on, so a later widening of the home cannot drift silently.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.toc.patterns import (
    RE_ITEM_EXACT,
    RE_ITEM_GROUPED,
    RE_ITEM_HEADING,
    RE_ITEM_HEADING_MARKER,
    RE_ITEM_INLINE,
    RE_ITEM_OR_NUMBERED_HEADING,
    RE_ITEM_SECTION_HEADING,
    RE_NOTE_CAPTION,
    RE_NOTE_GROUPED,
    RE_NOTE_HEADING,
    RE_NOTE_HEADING_CUE,
    RE_NOTE_REFERENCE,
    RE_NUMERIC_LABEL,
    RE_NUMERIC_RUN_IN,
    RE_PAREN_LABEL,
    RE_SECTION_REFERENCE,
    RE_SEE_REFERENCE,
    RE_TOC_ITEM,
)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("See Note 3 below", True),
        ("NOTES 10", True),
        ("Note 1.5", True),
        ("note", False),
        ("Noteworthy 3", False),
    ],
)
def test_note_reference_search(line: str, expected: bool) -> None:
    assert (RE_NOTE_REFERENCE.search(line) is not None) is expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Note 1. Basis of Presentation", True),
        ("NOTE 12 — Commitments", False),
        ("Note 1234. Too many digits", False),
        ("Notes 3. Title", False),
        ("Note 3:Title", True),
        ("Note 3", False),
        ("See Note 3. Title", False),
    ],
)
def test_note_caption_match(line: str, expected: bool) -> None:
    assert (RE_NOTE_CAPTION.match(line) is not None) is expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Item 1. Business", True),
        ("Item 1A Risk Factors", True),
        ("(1) Business", True),
        ("1. Business", True),
        ("Item 1", False),
        ("Items 1 and 2. Titles", False),
        ("Item 1.1 Reports", False),
    ],
)
def test_item_or_numbered_heading_search(line: str, expected: bool) -> None:
    assert (RE_ITEM_OR_NUMBERED_HEADING.search(line) is not None) is expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Notes to Financial Statements", True),
        ("NOTE 1 — BASIS", True),
        ("See Note 3 below", False),
        ("note 123abc", True),
    ],
)
def test_note_heading_cue_search(line: str, expected: bool) -> None:
    assert (RE_NOTE_HEADING_CUE.search(line) is not None) is expected


@pytest.mark.parametrize(
    ("line", "groups"),
    [
        ("NOTE 1. Basis of Presentation", ("1", "Basis of Presentation")),
        ("NOTE 1.5 Something", ("1", "5 Something")),
        ("NOTES 10, 11 and 12 Combined", ("10", ", 11 and 12 Combined")),
        ("Random prose line", None),
    ],
)
def test_note_heading_groups(line: str, groups: tuple[str, str] | None) -> None:
    match = RE_NOTE_HEADING.match(line)
    assert (None if match is None else match.groups()) == groups


@pytest.mark.parametrize(
    ("line", "group"),
    [
        ("NOTES 1, 2 and 3", "1, 2 and 3"),
        ("NOTES 1 & 3", "1 & 3"),
        ("NOTE 1", None),
    ],
)
def test_note_grouped_group(line: str, group: str | None) -> None:
    match = RE_NOTE_GROUPED.search(line)
    assert (None if match is None else match.group(1)) == group


@pytest.mark.parametrize(
    ("line", "groups"),
    [
        ("Item 1A. Risk Factors", ("1A", "Risk Factors")),
        ("Item 1.001 Weird", ("1", "001 Weird")),
        ("ITEM 7A.", ("7A", "")),
        ("Prose without a heading", None),
    ],
)
def test_item_heading_groups(line: str, groups: tuple[str, str] | None) -> None:
    match = RE_ITEM_HEADING.match(line)
    assert (None if match is None else match.groups()) == groups


@pytest.mark.parametrize(
    ("line", "group"),
    [
        ("ITEMS 1, 1A, and 1B", "1, 1A, and 1B"),
        ("ITEM 1", None),
    ],
)
def test_item_grouped_group(line: str, group: str | None) -> None:
    match = RE_ITEM_GROUPED.search(line)
    assert (None if match is None else match.group(1)) == group


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Item 1. Business", True),
        ("ITEM 1A. RISK FACTORS ...... 8", False),
        ("Item 2.01Resource", True),
        ("ITEM 15", True),
    ],
)
def test_item_exact_match(line: str, expected: bool) -> None:
    assert (RE_ITEM_EXACT.match(line) is not None) is expected


@pytest.mark.parametrize(
    ("line", "groups"),
    [
        ("Item 1.01 Entry", ("1.01", "Entry")),
        ("Item 2.01Resource", ("2.01", "Resource")),
        ("PART I Financial Information", None),
    ],
)
def test_item_section_heading_groups(line: str, groups: tuple[str, str] | None) -> None:
    match = RE_ITEM_SECTION_HEADING.match(line)
    assert (None if match is None else match.groups()) == groups


@pytest.mark.parametrize(
    ("line", "group"),
    [
        ("as described in Item 1.01 of the report", "1.01"),
        ("see ITEM 7A above", "7A"),
        ("Item 1.2345", "1"),
        ("no reference here", None),
    ],
)
def test_item_inline_group(line: str, group: str | None) -> None:
    match = RE_ITEM_INLINE.search(line)
    assert (None if match is None else match.group(1)) == group


@pytest.mark.parametrize(
    ("line", "group"),
    [
        ("pursuant to PART II of this report", "of this report"),
        ("PART IV", ""),
        ("see Item 1.01", ".01"),
        ("plain prose", None),
    ],
)
def test_section_reference_group(line: str, group: str | None) -> None:
    match = RE_SECTION_REFERENCE.search(line)
    assert (None if match is None else match.group(1)) == group


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("ITEMS 1 and 2.", True),
        ("ITEM 1A", False),
        ("ITEM 1A.", True),
        ("ITEM 12", False),
        ("| ITEM 5.", True),
    ],
)
def test_toc_item_match(line: str, expected: bool) -> None:
    assert (RE_TOC_ITEM.match(line) is not None) is expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("ITEM 1. Business", True),
        ("refer to ITEM 12A: Exhibits", True),
        ("ITEM 1 Business", False),
    ],
)
def test_item_heading_marker_search(line: str, expected: bool) -> None:
    assert (RE_ITEM_HEADING_MARKER.search(line) is not None) is expected


@pytest.mark.parametrize(
    ("line", "group"),
    [
        ("see item 4", "4"),
        ("See Row 12 for details", "12"),
        ("see items 4", None),
        ("oversee item 4", None),
    ],
)
def test_see_reference_group(line: str, group: str | None) -> None:
    match = RE_SEE_REFERENCE.search(line)
    assert (None if match is None else match.group(1)) == group


@pytest.mark.parametrize(
    ("line", "groups"),
    [
        ("1. Business", ("1", "Business")),
        ("1. business lowercase title", None),
        ("12A. Risk Factors", ("12A", "Risk Factors")),
    ],
)
def test_numeric_label_groups(line: str, groups: tuple[str, str] | None) -> None:
    match = RE_NUMERIC_LABEL.match(line)
    assert (None if match is None else match.groups()) == groups


@pytest.mark.parametrize(
    ("line", "groups"),
    [
        ("1. Business description here", ("1", "Business description here")),
        ("123. Too many digits", None),
    ],
)
def test_numeric_run_in_groups(line: str, groups: tuple[str, str] | None) -> None:
    match = RE_NUMERIC_RUN_IN.match(line)
    assert (None if match is None else match.groups()) == groups


@pytest.mark.parametrize(
    ("line", "groups"),
    [
        ("(1) Business", ("1", "Business")),
        ("(a) Letters", None),
        ("1) No paren open", None),
    ],
)
def test_paren_label_groups(line: str, groups: tuple[str, str] | None) -> None:
    match = RE_PAREN_LABEL.match(line)
    assert (None if match is None else match.groups()) == groups
