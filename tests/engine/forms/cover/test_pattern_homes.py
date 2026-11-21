"""Pins for the cover pattern homes (Wave 2B).
The non-alnum and whitespace recognizers live in
``foundation.text.patterns``; the line offset lives in the corridor.
"""

from __future__ import annotations

from edgar_sec.engine.forms.cover.boundary import corridor
from edgar_sec.engine.forms.cover.toc import analysis, finder, patterns


def test_toc_patterns_no_longer_defines_private_copies() -> None:
    assert not hasattr(patterns, "_RE_NON_ALPHANUM")
    assert not hasattr(patterns, "_RE_MULTI_SPACE")


def test_normalize_for_matching_verdicts() -> None:
    assert analysis.normalize_for_matching("Item 1A.  Business & Risk!") == (
        "item 1a business risk"
    )
    assert analysis.normalize_for_matching("") == ""
    assert analysis.normalize_for_matching("PART II — Other") == "part ii other"


def test_line_offset_binding_is_the_corridor_home() -> None:
    assert finder.line_offset is corridor.line_offset


def test_line_offset_verdicts() -> None:
    lines = ["ab", "cde", "f"]
    assert corridor.line_offset(lines, 0) == 0
    assert corridor.line_offset(lines, 1) == 3
    assert corridor.line_offset(lines, 2) == 7


def test_line_offset_at_end_of_lines() -> None:
    # The boundary the candidates list-builder cannot express: an offset
    # one past the last line is the total length, not an index error.
    lines = ["ab", "cde"]
    assert corridor.line_offset(lines, len(lines)) == 7
