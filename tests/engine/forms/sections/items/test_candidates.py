"""Tests for Part and Item candidate heading extraction."""

from __future__ import annotations

from edgar_sec.domain.forms.families.annual.taxonomy import FORM_10K_ITEMS
from edgar_sec.domain.forms.families.form_497.taxonomy import FORM_497_ITEMS
from edgar_sec.domain.forms.families.form_nq.taxonomy import FORM_NQ_ITEMS
from edgar_sec.domain.forms.families.form_sd.taxonomy import FORM_SD_ITEMS
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


def test_title_keyed_item_candidate_joins_by_title() -> None:
    """A title-keyed taxonomy joins ITEM candidates through their titles."""
    lines = [
        "Item 1. Schedule of Investments",
        "Item 2. Controls and Procedures",
        "Item 3. Exhibits",
    ]
    cands = extract_section_candidates(lines, taxonomy_items=FORM_NQ_ITEMS)
    assert [c.identifiers for c in cands] == [
        ("SCHEDULE OF INVESTMENTS",),
        ("CONTROLS AND PROCEDURES",),
        ("EXHIBITS",),
    ]


def test_item_keyed_candidate_keeps_number_when_title_is_shared() -> None:
    """SD items 1.02 and 3.01 share the title "Exhibits"; each ITEM
    candidate keeps the filer's own number."""
    lines = ["Item 1.02 Exhibits", "Item 3.01 Exhibits"]
    cands = extract_section_candidates(lines, taxonomy_items=FORM_SD_ITEMS)
    assert [c.identifiers for c in cands] == [("1.02",), ("3.01",)]


def test_title_keyed_item_candidate_en_dash_separator() -> None:
    lines = ["Item 1 \u2013 Schedule of Investments"]
    cands = extract_section_candidates(lines, taxonomy_items=FORM_NQ_ITEMS)
    assert len(cands) == 1
    assert cands[0].identifiers == ("SCHEDULE OF INVESTMENTS",)
    assert cands[0].title == "Schedule of Investments"


def test_composite_running_head_candidate() -> None:
    """A taxonomy title riding in a composite running head is a heading;
    the same title opening a prose sentence is not.
    """
    lines = [
        "Portfolio of investments\u2014April 30, 2018  Wells Fargo Fund  9",
        "10  Wells Fargo Fund  Portfolio of investments\u2014April 30, 2018",
        "Financial highlights are the responsibility of management.",
    ]
    from edgar_sec.domain.forms.families.form_ncsr.taxonomy import FORM_NCSR_ITEMS

    cands = extract_section_candidates(lines, taxonomy_items=FORM_NCSR_ITEMS)
    assert [c.line_number for c in cands] == [0, 1]
    assert all(c.identifiers == ("PORTFOLIO OF INVESTMENTS",) for c in cands)


def test_composite_embedded_mentions_are_not_headings() -> None:
    """A title embedded in an appendix caption or a quoted cross-reference
    is a mention, not a heading.
    """
    lines = [
        "Appendix C --  Description of Principal Risks of the Funds    33",
        'See "Underwriting."',
        "Fund's investment objective and policies are described below.",
        "Principal risks of the Fund...........   35",
        "Underwriting Discount(2)                      $250                $1,300,000",
        "Risk Factors and Special",
        "Risk Factors and Special Considerations                                      10",
        "Underwriters.",
        "Principal risks of the Fund             73",
        "Use of Proceeds                         S-6",
        "Underwriting (Conflicts of Interest)                               S-106",
    ]
    cands = extract_section_candidates(lines, taxonomy_items=FORM_497_ITEMS)
    assert cands == []


def test_composite_toc_row_with_status_qualifier_is_not_a_heading() -> None:
    """A TOC row whose only signal is a status qualifier is not a heading."""
    lines = ["Statement of Operations (Unaudited)                                    9"]
    from edgar_sec.domain.forms.families.form_ncsr.taxonomy import FORM_NCSR_ITEMS

    cands = extract_section_candidates(lines, taxonomy_items=FORM_NCSR_ITEMS)
    assert cands == []


def test_composite_cross_reference_running_head_is_not_a_heading() -> None:
    """A cross-reference phrase fused into a running head is a mention."""
    lines = ["FOXBY CORP.    4     See notes to financial statements."]
    from edgar_sec.domain.forms.families.form_ncsr.taxonomy import FORM_NCSR_ITEMS

    cands = extract_section_candidates(lines, taxonomy_items=FORM_NCSR_ITEMS)
    assert cands == []


def test_composite_bare_toc_row_is_not_a_heading() -> None:
    """A title plus a bare page number carries no heading signal."""
    lines = ["Portfolio of investments                                       9"]
    from edgar_sec.domain.forms.families.form_ncsr.taxonomy import FORM_NCSR_ITEMS

    cands = extract_section_candidates(lines, taxonomy_items=FORM_NCSR_ITEMS)
    assert cands == []
