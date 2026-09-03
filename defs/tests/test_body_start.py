"""Contract tests for the forward body-start detector."""

from __future__ import annotations

import importlib

import pytest

from defs.sec_forms.cover import get_profile

cover_mod = importlib.import_module("defs.sec_forms.cover")

find_body_start = cover_mod.find_body_start
BodyStart = cover_mod.BodyStart
BodyAnchorType = cover_mod.BodyAnchorType

# The full annual body pack exercises the lexical tiers and the semantic
# heading scan together, matching the production normalizer input.
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
    from defs.sec_forms.cover.toc import TocSpan

    text = ANNUAL_COVER + (
        "\n\nTABLE OF CONTENTS\n"
        "ITEM 1. BUSINESS .......................... 1\n"
        "\nPART I\nItem 1. Business\n\n"
        "The Company was incorporated in Delaware and manufactures widgets for "
        "customers worldwide. It provides products and services to markets.\n"
    )
    # The dot-leader TOC row would otherwise read as an exact ITEM heading;
    # the explicit span marks lines 12-13 as TOC context (end_line exclusive).
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


def test_body_start_evidence_recorded() -> None:
    text = ANNUAL_COVER + (
        "\n\nPART I\n\nItem 1. Business\n\n"
        "The Company was incorporated in Delaware and manufactures widgets for customers "
        "worldwide.\n"
    )
    result = find_body_start(text, cover_end=11, toc_end=None, evidence=ANNUAL_PACK)
    names = {e.name for e in result.evidence}
    assert "structural_body_anchor" in names


def test_delayed_flag_set_when_earlier_candidates_rejected() -> None:
    text = ANNUAL_COVER + (
        "\n\nPART I\nand Part II are incorporated by reference.\n\n"
        "PART I\n\nItem 1. Business\n\n"
        "The Company was incorporated in Delaware and manufactures widgets for customers "
        "worldwide.\n"
    )
    result = find_body_start(text, cover_end=11, toc_end=None, evidence=ANNUAL_PACK)
    assert result.delayed is True
    assert len(result.rejection_reasons) >= 1


def test_substantive_prose_without_heading() -> None:
    text = ANNUAL_COVER + (
        "\n\nThe Company was incorporated in Delaware in 1985 and manufactures widgets "
        "for industrial customers throughout North America and Europe. It provides "
        "products to customers worldwide through its market segments and operates "
        "manufacturing facilities.\n"
    )
    result = find_body_start(text, cover_end=11, toc_end=None, evidence=ANNUAL_PACK)
    assert result.line is not None
    assert result.anchor_type in (
        BodyAnchorType.SUBSTANTIVE.value,
        BodyAnchorType.STRUCTURAL.value,
    )


def test_item_one_a_without_item_one() -> None:
    text = ANNUAL_COVER + (
        "\n\nPART I\n\nItem 1A. Risk Factors\n\n"
        "The Company faces competition in all of its market segments and operates "
        "manufacturing facilities worldwide. It provides products to customers and "
        "suppliers through integrated operations.\n"
    )
    result = find_body_start(text, cover_end=11, toc_end=None, evidence=ANNUAL_PACK)
    assert result.line is not None
    assert result.anchor_type == BodyAnchorType.STRUCTURAL.value


def test_adversarial_part_iii_hereof_not_body() -> None:
    text = ANNUAL_COVER + (
        "\n\nDocuments incorporated by reference: see Part III hereof.\n\n"
        "PART I\n\nItem 1. Business\n\n"
        "The Company was incorporated in Delaware and manufactures widgets for customers "
        "worldwide.\n"
    )
    result = find_body_start(text, cover_end=11, toc_end=None, evidence=ANNUAL_PACK)
    lines = text.splitlines()
    assert result.line is not None
    assert lines[result.line].strip() == "PART I"


def test_adversarial_multi_reference_not_body() -> None:
    text = ANNUAL_COVER + (
        "\n\nParts I, II, and III are incorporated by reference.\n\n"
        "PART I\n\nItem 1. Business\n\n"
        "The Company was incorporated in Delaware and manufactures widgets for customers "
        "worldwide.\n"
    )
    result = find_body_start(text, cover_end=11, toc_end=None, evidence=ANNUAL_PACK)
    lines = text.splitlines()
    assert result.line is not None
    assert lines[result.line].strip() == "PART I"


def test_body_start_dataclass_is_frozen() -> None:
    result = BodyStart(
        line=10,
        heading_line=10,
        first_unit_line=12,
        anchor_type="structural",
        confidence=0.9,
    )
    assert result.line == 10
    with pytest.raises(AttributeError):
        result.line = 20  # type: ignore[misc]


def test_body_start_evidence_dataclass_is_frozen() -> None:
    evidence = cover_mod.BodyStartEvidence(
        name="test", strength=0.5, line=10, details="test"
    )
    assert evidence.name == "test"
    with pytest.raises(AttributeError):
        evidence.name = "other"  # type: ignore[misc]


def test_anchor_type_enum_values() -> None:
    assert BodyAnchorType.STRUCTURAL.value == "structural"
    assert BodyAnchorType.SEMANTIC.value == "semantic"
    assert BodyAnchorType.SUBSTANTIVE.value == "substantive"
    assert BodyAnchorType.UNKNOWN.value == "unknown"


def test_search_window_respected() -> None:
    text = ANNUAL_COVER + "\n" + "\n".join(f"Filler line {i}" for i in range(500))
    text += "\n\nPART I\n\nItem 1. Business\n\nThe Company manufactures widgets.\n"
    result = find_body_start(
        text, cover_end=11, toc_end=None, evidence=ANNUAL_PACK, search_window=50
    )
    assert result.line is None
    assert result.anchor_type == BodyAnchorType.UNKNOWN.value


def test_cover_end_zero_starts_from_beginning() -> None:
    text = (
        "PART I\n\nItem 1. Business\n\n"
        "The Company was incorporated in Delaware and manufactures widgets for customers "
        "worldwide.\n"
    )
    result = find_body_start(text, cover_end=0, toc_end=None, evidence=ANNUAL_PACK)
    assert result.line is not None


def test_semantic_heading_matches_without_hyphen() -> None:
    text = ANNUAL_COVER + (
        "\n\nThe Company's forward looking statements describe its operations "
        "and strategy. The Company was incorporated in Delaware and "
        "manufactures widgets for industrial customers throughout North "
        "America and Europe. It provides products to customers worldwide.\n"
    )
    result = find_body_start(text, cover_end=11, toc_end=None, evidence=ANNUAL_PACK)
    assert result.line is not None
