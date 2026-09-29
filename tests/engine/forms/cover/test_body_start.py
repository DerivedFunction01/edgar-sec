"""Tests for forward body-start detection."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.body_start import find_body_start
from edgar_sec.engine.forms.cover.models import BodyAnchorType

PROSE = """\
The Company was founded in 1994 and is a leading provider of industrial \
widgets. It operates three manufacturing facilities and employs \
approximately 4,200 people worldwide."""

DOC = (
    """\
ACME INDUSTRIAL WIDGETS, INC.
Commission File Number: 001-14103

PART I

ITEM 1. Business

"""
    + PROSE
    + """

ITEM 1A. Risk Factors

Investors should note the following risk factors, which could materially \
affect the results of the Company. The Company operates in a competitive \
industry worldwide."""
)


def test_empty_document() -> None:
    result = find_body_start("", cover_end=0)
    assert result.anchor_type == BodyAnchorType.UNKNOWN.value
    assert result.confidence == 0.0
    assert result.reason == "empty document"


def test_structural_anchor_after_cover() -> None:
    result = find_body_start(DOC, cover_end=2)
    assert result.anchor_type == BodyAnchorType.STRUCTURAL.value
    assert result.line is not None
    assert result.heading_line is not None
    assert result.first_unit_line is not None
    assert result.first_unit_line > 2
    assert result.confidence == 0.9


def test_structural_anchor_requires_following_prose() -> None:
    doc = "PART I\n\nITEM 1\n\n\nPART II"
    result = find_body_start(doc, cover_end=0)
    assert result.first_unit_line is None
    assert result.anchor_type == BodyAnchorType.UNKNOWN.value
    assert any("no substantive prose" in reason for reason in result.rejection_reasons)


def test_substantive_anchor_without_structural_heading() -> None:
    doc = f"cover line one\ncover line two\n\n{PROSE}\n\n{PROSE}"
    result = find_body_start(doc, cover_end=0)
    assert result.anchor_type == BodyAnchorType.SUBSTANTIVE.value
    assert result.heading_line is None
    assert result.first_unit_line is not None
    assert result.confidence == 0.6


def test_semantic_anchor_from_section_heading() -> None:
    doc = (
        "cover\n\nManagement's Discussion and Analysis of Financial Condition\n\n"
        + PROSE
    )
    result = find_body_start(doc, cover_end=0)
    assert result.anchor_type == BodyAnchorType.SEMANTIC.value
    assert result.first_unit_line is not None


def test_cover_only_cover_end_returns_unknown() -> None:
    doc = "ACME\nCommission File Number: 1\nTrading Symbol"
    result = find_body_start(doc, cover_end=3)
    assert result.first_unit_line is None
    assert result.confidence == 0.0
    assert result.reason


def test_toc_rows_are_not_body_anchors() -> None:
    doc = (
        """\
TABLE OF CONTENTS
ITEM 1. Business .......................... 1
ITEM 1A. Risk Factors .................... 5

PART I

ITEM 1. Business

"""
        + PROSE
    )
    result = find_body_start(doc, cover_end=0)
    lines = doc.splitlines()
    assert result.line is not None
    assert result.line == lines.index("PART I")


def test_search_window_is_bounded() -> None:
    lines = ["cover", *["filler"] * 500, "PART I", "", "ITEM 1. Business", "", PROSE]
    result = find_body_start("\n".join(lines), cover_end=1, search_window=20)
    assert result.first_unit_line is None


def test_evidence_is_recorded_for_rejections() -> None:
    doc = (
        """\
ITEM 1
hereunder. continuation prose

PART I

ITEM 1. Business

"""
        + PROSE
    )
    result = find_body_start(doc, cover_end=0)
    names = {item.name for item in result.evidence}
    assert "structural_body_anchor" in names
    assert result.delayed is True
