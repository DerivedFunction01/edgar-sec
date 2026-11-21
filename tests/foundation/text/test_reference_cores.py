"""Pins for the homed Item/Part reference cores (mirror cure, Option A).
Healing composes the cores verbatim (its boundary pattern is byte-identical);
the toc side's keyword-case-only delta is pinned below, verdicts unchanged.
"""

from __future__ import annotations

from edgar_sec.engine.tables.toc.patterns import RE_ITEM_REFERENCE, RE_PART_REFERENCE
from edgar_sec.foundation.text.healing import NEGATIVE_BOUNDARY_RE
from edgar_sec.foundation.text.patterns import ITEM_REFERENCE_CORE, PART_REFERENCE_CORE


def test_cores_are_the_verbatim_foundation_spellings() -> None:
    assert ITEM_REFERENCE_CORE == r"Item\s+\d+"
    assert PART_REFERENCE_CORE == r"Part\s+"


def test_toc_patterns_take_only_the_keyword_case_delta() -> None:
    assert RE_ITEM_REFERENCE.pattern == r"\bItem\s+\d+(?:\.\d+)*[A-Z]?\b"
    assert RE_PART_REFERENCE.pattern == r"\bPart\s+(?:[IVXLCDM]+|\d+)\b"


def test_healing_boundary_still_carries_the_verbatim_terms() -> None:
    assert r"Item\s+\d+" in NEGATIVE_BOUNDARY_RE.pattern
    assert r"Part\s+[IVX]+" in NEGATIVE_BOUNDARY_RE.pattern


def test_item_case_table_holds_on_both_sides() -> None:
    # Item 1A: toc takes the letter suffix; healing takes the bare term.
    toc = RE_ITEM_REFERENCE.search("Item 1A")
    assert toc is not None and toc.group(0) == "Item 1A"
    heal = NEGATIVE_BOUNDARY_RE.search("Item 1A")
    assert heal is not None and heal.group(0) == "Item 1"
    # Item 1.5: toc takes the dotted tail; healing takes the bare term.
    toc = RE_ITEM_REFERENCE.search("Item 1.5")
    assert toc is not None and toc.group(0) == "Item 1.5"
    heal = NEGATIVE_BOUNDARY_RE.search("Item 1.5")
    assert heal is not None and heal.group(0) == "Item 1"
    # Trailing period: neither side consumes it.
    toc = RE_ITEM_REFERENCE.search("Item 1.")
    assert toc is not None and toc.group(0) == "Item 1"
    heal = NEGATIVE_BOUNDARY_RE.search("Item 1.")
    assert heal is not None and heal.group(0) == "Item 1"


def test_part_case_table_holds_on_both_sides() -> None:
    # Part 2: toc's digit branch matches; healing's roman class does not.
    toc = RE_PART_REFERENCE.search("Part 2")
    assert toc is not None and toc.group(0) == "Part 2"
    assert NEGATIVE_BOUNDARY_RE.search("Part 2") is None
    # Part L: toc's wider roman class matches; healing's [IVX] does not.
    toc = RE_PART_REFERENCE.search("Part L")
    assert toc is not None and toc.group(0) == "Part L"
    assert NEGATIVE_BOUNDARY_RE.search("Part L") is None
    # Part IV: both sides match in full.
    toc = RE_PART_REFERENCE.search("Part IV")
    assert toc is not None and toc.group(0) == "Part IV"
    heal = NEGATIVE_BOUNDARY_RE.search("Part IV")
    assert heal is not None and heal.group(0) == "Part IV"
    # Part IVL: toc takes the full numeral; healing takes its IV prefix.
    toc = RE_PART_REFERENCE.search("Part IVL")
    assert toc is not None and toc.group(0) == "Part IVL"
    heal = NEGATIVE_BOUNDARY_RE.search("Part IVL")
    assert heal is not None and heal.group(0) == "Part IV"
