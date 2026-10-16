"""Tests for Part and Item section sequence detection."""

from __future__ import annotations

from edgar_sec.domain.forms.families.annual.taxonomy import FORM_10K_ITEMS
from edgar_sec.engine.forms.sections.items.detector import detect_section_sequence


def test_detect_monotonic_section_sequence() -> None:
    text = "\n".join(
        [
            "Item 1. Business",
            "This is the business description.",
            "Item 1A. Risk Factors",
            "These are the risk factors.",
            "Item 2. Properties",
            "These are properties.",
        ]
    )
    seq = detect_section_sequence(text, family="10-K", taxonomy_items=FORM_10K_ITEMS)
    labels = [s.item_identifier for s in seq.sections]
    assert labels == ["ITEM 1", "ITEM 1A", "ITEM 2"]
    assert seq.anachronistic_rejections == 0


def test_rejects_backward_prose_cross_reference() -> None:
    text = "\n".join(
        [
            "Item 1. Business",
            "Business prose.",
            "Item 7. Management Discussion and Analysis",
            "MD&A prose referring back to Item 1 for context.",
            "Item 1.",
            "More MD&A details.",
            "Item 8. Financial Statements",
            "Statements follow.",
        ]
    )
    seq = detect_section_sequence(text, family="10-K", taxonomy_items=FORM_10K_ITEMS)
    labels = [s.item_identifier for s in seq.sections]
    assert labels == ["ITEM 1", "ITEM 7", "ITEM 8"]
    assert seq.anachronistic_rejections >= 1


def test_rejects_non_contiguous_prose_lists() -> None:
    text = "\n".join(
        [
            "Item 1. Business",
            "Disclosures.",
            "Items 1A and 1C",
            "Disjoint list.",
            "Item 2. Properties",
            "Properties.",
        ]
    )
    seq = detect_section_sequence(text, family="10-K", taxonomy_items=FORM_10K_ITEMS)
    labels = [s.item_identifier for s in seq.sections]
    assert "ITEM 1A" not in labels
    assert seq.non_contiguous_rejections >= 1


def test_skips_dense_pseudo_toc_cluster() -> None:
    text = "\n".join(
        [
            "Item 1. Business",
            "Item 1A. Risk Factors",
            "Item 2. Properties",
            "Item 3. Legal Proceedings",
            "",
            "Substantive document begins here.",
            "Item 1. Business",
            "Real business narrative goes here for dozens of lines.",
            "Item 1A. Risk Factors",
            "Real risks go here.",
        ]
    )
    seq = detect_section_sequence(text, family="10-K", taxonomy_items=FORM_10K_ITEMS)
    labels = [s.item_identifier for s in seq.sections]
    assert labels == ["ITEM 1", "ITEM 1A"]
    assert seq.sections[0].start_line >= 6
