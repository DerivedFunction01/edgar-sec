"""Compiled table patterns: block detection, footnote shape, hidden-element style.

Plus the three patterns the boundary resolver and the reflow intro policy read.
"""

from __future__ import annotations

from edgar_sec.engine.tables.patterns import (
    COLUMN_DASH_RULE_RE,
    FOOTNOTE_RE,
    HIDDEN_ELEMENT_STYLE_RE,
    RE_TABLE_BLOCK,
    _RE_TABLE_INTRO_CUE,
    UNITS_LABEL_RE,
)


def test_table_block_is_whole_line_tagged_and_dot_all() -> None:
    assert RE_TABLE_BLOCK.findall("a <TABLE>x\ny</TABLE> b") == ["<TABLE>x\ny</TABLE>"]


def test_table_block_does_not_match_a_lowercase_tag() -> None:
    assert RE_TABLE_BLOCK.findall("<table>x</table>") == []


def test_footnote_shape_accepts_star_paren_and_digit_markers() -> None:
    assert FOOTNOTE_RE.fullmatch("(1)") is not None
    assert FOOTNOTE_RE.fullmatch("*") is not None
    assert FOOTNOTE_RE.fullmatch("(a)") is not None
    assert FOOTNOTE_RE.fullmatch("Percent of class") is None


def test_hidden_element_style_covers_display_none_and_visibility_hidden() -> None:
    assert HIDDEN_ELEMENT_STYLE_RE.search("display: none") is not None
    assert HIDDEN_ELEMENT_STYLE_RE.search("VISIBILITY:   HIDDEN") is not None
    assert HIDDEN_ELEMENT_STYLE_RE.search("color: red") is None


def test_column_dash_rule_needs_at_least_two_short_groups() -> None:
    assert COLUMN_DASH_RULE_RE.match("------   ------   ------") is not None
    assert COLUMN_DASH_RULE_RE.match("---------") is None
    assert COLUMN_DASH_RULE_RE.match("--------") is None
    assert COLUMN_DASH_RULE_RE.match("---   ----   ---") is not None
    assert COLUMN_DASH_RULE_RE.match("--------  ---------") is not None


def test_column_dash_rule_rejects_prose_and_data_rows() -> None:
    assert COLUMN_DASH_RULE_RE.match("Revenue by segment       2024") is None
    assert COLUMN_DASH_RULE_RE.match("Total                    300") is None


def test_units_label_matches_every_documented_scale_qualifier() -> None:
    for label in (
        "(in thousands)",
        "(In Thousands)",
        "(dollars in millions)",
        "(Dollars in Millions, except per share data)",
        "(amounts in thousands)",
        "(in shares)",
        "(in percent)",
    ):
        assert UNITS_LABEL_RE.search(label) is not None, label


def test_units_label_rejects_an_unparenthetical_or_unscaled_phrase() -> None:
    assert UNITS_LABEL_RE.search("in thousands") is None
    assert UNITS_LABEL_RE.search("(in furlongs)") is None
    assert UNITS_LABEL_RE.search("(the following table)") is None


def test_table_intro_cue_recognises_the_documented_cue_families() -> None:
    for cue in (
        "The following table presents the results",
        "the following schedule summarizes revenue",
        "The schedule above sets forth the amounts",
        "As follows, the amounts are given",
        "Set forth in the following are the amounts",
        "Presented below are the amounts",
        "consists of the following amounts",
    ):
        assert _RE_TABLE_INTRO_CUE.search(cue) is not None, cue


def test_table_intro_cue_rejects_filing_specific_prose() -> None:
    assert (
        _RE_TABLE_INTRO_CUE.search("The fair value was estimated using assumptions")
        is None
    )
    assert _RE_TABLE_INTRO_CUE.search("We are an enterprise software company") is None
