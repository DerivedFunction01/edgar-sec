"""Unit and contract tests for edgar_sec.engine.forms.cover.body_start."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.body_start import find_body_start
from edgar_sec.engine.forms.cover.models import BodyAnchorType
from edgar_sec.engine.forms.cover.profiles import get_profile
from edgar_sec.engine.forms.cover.toc.models import TocSpan

ANNUAL_PACK = get_profile("10-K").body_evidence

ANNUAL_COVER = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
WASHINGTON, D.C. 20549
FORM 10-K
For the fiscal year ended December 31, 2024
Commission file number 001-13665
ACME CORPORATION
(Exact name of registrant as specified in its charter)
Delaware          12-3456789
(State or other jurisdiction of incorporation or organization)
"""


def test_structural_part_one_with_body_prose() -> None:
    text = ANNUAL_COVER + (
        "\n\nPART I\n\nItem 1. Business\n\n"
        "The Company was incorporated in Delaware in 1985 and manufactures widgets for "
        "industrial customers throughout North America and Europe. It provides products "
        "to customers worldwide.\n"
    )
    result = find_body_start(text, cover_end=11, toc_end=None, evidence=ANNUAL_PACK)
    lines = text.splitlines()
    assert result.line is not None
    assert lines[result.line].strip() == "PART I"
    assert result.anchor_type == BodyAnchorType.STRUCTURAL.value
    assert result.confidence >= 0.8


def test_toc_item_one_not_body_root() -> None:
    text = ANNUAL_COVER + (
        "\n\nTABLE OF CONTENTS\n"
        "ITEM 1. BUSINESS .......................... 1\n"
        "ITEM 1A. RISK FACTORS ..................... 8\n"
        "ITEM 2. PROPERTIES ....................... 15\n"
        "\nPART I\nItem 1. Business\n\n"
        "The Company was incorporated in Delaware and manufactures widgets for customers "
        "worldwide. It provides products and services through market segments.\n"
    )
    result = find_body_start(text, cover_end=11, toc_end=16, evidence=ANNUAL_PACK)
    lines = text.splitlines()
    assert result.line is not None
    assert result.line >= 16
    assert lines[result.line].strip() == "PART I"


def test_toc_span_units_stay_ineligible() -> None:
    text = ANNUAL_COVER + (
        "\n\nTABLE OF CONTENTS\n"
        "ITEM 1. BUSINESS .......................... 1\n"
        "\nPART I\nItem 1. Business\n\n"
        "The Company was incorporated in Delaware and manufactures widgets for "
        "customers worldwide. It provides products and services to markets.\n"
    )
    toc_span = TocSpan(
        start_line=12,
        end_line=14,
        start_offset=0,
        end_offset=0,
        method="test",
        confidence=0.9,
    )
    result = find_body_start(
        text,
        cover_end=11,
        toc_end=None,
        evidence=ANNUAL_PACK,
        toc_span=toc_span,
    )
    lines = text.splitlines()
    assert result.line is not None
    assert result.line >= 14
    assert lines[result.line].strip() == "PART I"


def test_part_one_followed_by_lowercase_continuation_rejected() -> None:
    text = ANNUAL_COVER + (
        "\n\nPART I\nand Part II of the proxy statement are incorporated by reference.\n\n"
        "PART I\n\nItem 1. Business\n\n"
        "The Company was incorporated in Delaware and manufactures widgets for customers "
        "worldwide.\n"
    )
    result = find_body_start(text, cover_end=11, toc_end=None, evidence=ANNUAL_PACK)
    assert result.line is not None
    assert result.delayed is True
    assert result.line > 11


def test_omitted_after_item_one_skipped() -> None:
    text = ANNUAL_COVER + (
        "\n\nPART I\n\nItem 1. Business\n\nOmitted.\n\n"
        "Item 1A. Risk Factors\n\n"
        "The Company faces competition in all of its market segments and operates "
        "manufacturing facilities worldwide. It provides products to customers and "
        "suppliers through integrated operations.\n"
    )
    result = find_body_start(text, cover_end=11, toc_end=None, evidence=ANNUAL_PACK)
    assert result.line is not None
    assert result.anchor_type == BodyAnchorType.STRUCTURAL.value


def test_not_applicable_after_item_one_skipped() -> None:
    text = ANNUAL_COVER + (
        "\n\nPART I\n\nItem 1. Business\n\nNot applicable.\n\n"
        "Item 2. Properties\n\n"
        "The Company operates manufacturing facilities and provides products to customers "
        "worldwide through its market segments.\n"
    )
    result = find_body_start(text, cover_end=11, toc_end=None, evidence=ANNUAL_PACK)
    assert result.line is not None


def test_no_reliable_candidate_returns_unknown() -> None:
    text = (
        ANNUAL_COVER
        + "\n"
        + "\n".join(f"Cover term {i} pursuant herein." for i in range(100))
    )
    result = find_body_start(text, cover_end=11, toc_end=None, evidence=ANNUAL_PACK)
    assert result.line is None
    assert result.anchor_type == BodyAnchorType.UNKNOWN.value
    assert result.confidence == 0.0


def test_empty_document_returns_unknown() -> None:
    result = find_body_start("", cover_end=None, toc_end=None, evidence=ANNUAL_PACK)
    assert result.line is None
    assert result.anchor_type == BodyAnchorType.UNKNOWN.value


def test_structural_item_one_with_false_table_prose() -> None:
    # Double-spaced punctuation makes page_markers.units call this block a table, which
    # body_start recognises as narrative prose.
    text = ANNUAL_COVER + (
        "\n\nITEM 1. BUSINESS\n\n"
        "Galileo International, Inc. (herein referred to as the Company), incorporated  in\n"
        "Delaware in 1997, operates globally.  We believe that in-depth knowledge of local\n"
        "travel markets is essential.  The Company intends to provide quality solutions\n"
        "to customers worldwide.\n"
    )
    result = find_body_start(text, cover_end=11, toc_end=None, evidence=ANNUAL_PACK)
    lines = text.splitlines()
    assert result.line is not None
    assert lines[result.line].strip() == "ITEM 1. BUSINESS"
    assert result.anchor_type == BodyAnchorType.STRUCTURAL.value
    assert result.first_unit_line is not None
