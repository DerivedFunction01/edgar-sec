"""Tests for Part and Item candidate heading extraction."""

from __future__ import annotations

from edgar_sec.domain.forms.families.annual.taxonomy import FORM_10K_ITEMS
from edgar_sec.engine.forms.sections.items.candidates import extract_section_candidates
from edgar_sec.engine.forms.sections.models import CandidateKind


def test_extract_standard_item_candidate() -> None:
    lines = ["Item 1. Business", "Substantive prose follows here."]
    cands = extract_section_candidates(lines, taxonomy_items=FORM_10K_ITEMS)
    assert len(cands) == 1
    assert cands[0].kind == CandidateKind.STANDARD
    assert cands[0].identifiers == ("1",)
    assert cands[0].title == "Business"


def test_extract_grouped_item_candidate() -> None:
    lines = ["Items 1, 1A, 1B, and 1C. Combined Disclosures"]
    cands = extract_section_candidates(lines, taxonomy_items=FORM_10K_ITEMS)
    assert len(cands) == 1
    assert cands[0].kind == CandidateKind.GROUPED
    assert cands[0].identifiers == ("1", "1A", "1B", "1C")


def test_extract_numeric_label_with_taxonomy_title() -> None:
    lines = ["1. Business", "Company operations description."]
    cands = extract_section_candidates(lines, taxonomy_items=FORM_10K_ITEMS)
    assert len(cands) == 1
    assert cands[0].kind == CandidateKind.NUMERIC
    assert cands[0].identifiers == ("1",)


def test_flags_preceding_continuation_preposition() -> None:
    lines = ["...in accordance with the rules under", "Item 1."]
    cands = extract_section_candidates(lines, taxonomy_items=FORM_10K_ITEMS)
    assert len(cands) == 1
    assert cands[0].preceded_by_continuation is True


def test_identifies_omitted_spv_items() -> None:
    lines = [
        "Item 1. [Omitted]",
        "Item 1A. Risk Factors - Not Applicable",
        "Item 2. Properties - None",
    ]
    cands = extract_section_candidates(lines, taxonomy_items=FORM_10K_ITEMS)
    assert len(cands) == 3
    assert all(c.is_omitted for c in cands)
