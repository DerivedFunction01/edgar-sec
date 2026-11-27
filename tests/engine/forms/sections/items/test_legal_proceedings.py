"""Tests for Item 3 legal proceedings span and disposition emission."""

from __future__ import annotations

from edgar_sec.domain.forms.families.annual.taxonomy import FORM_10K_ITEMS
from edgar_sec.engine.forms.sections.items.detector import detect_section_sequence
from edgar_sec.engine.forms.sections.items.legal_proceedings import (
    extract_legal_proceedings,
)
from edgar_sec.engine.forms.sections.models import LegalProceedingsDisposition


def _emit(lines: list[str]):
    text = "\n".join(lines)
    seq = detect_section_sequence(text, family="10-K", taxonomy_items=FORM_10K_ITEMS)
    return extract_legal_proceedings(seq, text), seq, text


def _framed(item3_lines: list[str]) -> list[str]:
    return [
        "Item 2. Properties",
        "Properties prose.",
        *item3_lines,
        "Item 4. Mine Safety Disclosures",
        "Not applicable.",
    ]


def test_disposition_vocabulary_matches_the_priced_classes() -> None:
    assert {d.value for d in LegalProceedingsDisposition} == {
        "none",
        "omitted",
        "cross_reference",
        "substantive",
    }


def test_run_in_none_stub_emits_span_and_none_disposition() -> None:
    emission, seq, text = _emit(_framed(["Item 3. Legal Proceedings. None."]))
    assert emission is not None
    section = seq.get("ITEM 3")
    assert section is not None
    assert (emission.start_line, emission.end_line) == (
        section.start_line,
        section.end_line,
    )
    assert (emission.start_char, emission.end_char) == (
        section.start_char,
        section.end_char,
    )
    assert text[emission.start_char : emission.end_char].rstrip() == (
        "Item 3. Legal Proceedings. None."
    )
    assert emission.disposition is LegalProceedingsDisposition.NONE


def test_all_caps_omitted_form() -> None:
    emission, _, _ = _emit(_framed(["ITEM 3. LEGAL PROCEEDINGS . Omitted"]))
    assert emission is not None
    assert emission.disposition is LegalProceedingsDisposition.OMITTED


def test_parenthesized_omitted_marker_in_heading() -> None:
    emission, _, _ = _emit(_framed(["Item 3. Legal Proceedings (Omitted)"]))
    assert emission is not None
    assert emission.disposition is LegalProceedingsDisposition.OMITTED


def test_not_applicable_stub_on_following_line() -> None:
    emission, _, _ = _emit(_framed(["Item 3. Legal Proceedings", "Not applicable."]))
    assert emission is not None
    assert emission.disposition is LegalProceedingsDisposition.NONE


def test_heading_only_section_is_a_none_stub() -> None:
    emission, _, _ = _emit(_framed(["Item 3. Legal Proceedings"]))
    assert emission is not None
    assert emission.disposition is LegalProceedingsDisposition.NONE


def test_title_carried_on_its_own_line() -> None:
    emission, _, _ = _emit(_framed(["Item 3.", "Legal Proceedings", "None."]))
    assert emission is not None
    assert emission.disposition is LegalProceedingsDisposition.NONE


def test_incorporation_by_reference_is_a_cross_reference() -> None:
    emission, _, _ = _emit(
        _framed(
            [
                "Item 3. Legal Proceedings",
                "The information required by this item is incorporated by "
                "reference to the information set forth under the caption "
                '"Legal Proceedings" in the Notes to Consolidated Financial '
                "Statements included in Item 8 of this report.",
            ]
        )
    )
    assert emission is not None
    assert emission.disposition is LegalProceedingsDisposition.CROSS_REFERENCE


def test_short_negative_prose_is_substantive() -> None:
    emission, _, _ = _emit(
        _framed(
            [
                "Item 3. Legal Proceedings",
                "We are not a party to any legal proceedings that are "
                "expected to have a material adverse effect on our "
                "financial condition or results of operations.",
            ]
        )
    )
    assert emission is not None
    assert emission.disposition is LegalProceedingsDisposition.SUBSTANTIVE


def test_structured_proceedings_disclosure_is_substantive() -> None:
    emission, _, _ = _emit(
        _framed(
            [
                "Item 3. Legal Proceedings",
                "I. Legal Proceedings. The Company is a defendant in a "
                "number of actions filed in state and federal courts. "
                "The plaintiffs allege violations of environmental laws "
                "and seek compensatory damages in unspecified amounts.",
            ]
        )
    )
    assert emission is not None
    assert emission.disposition is LegalProceedingsDisposition.SUBSTANTIVE


def test_incidental_note_reference_does_not_make_a_cross_reference() -> None:
    emission, _, _ = _emit(
        _framed(
            [
                "Item 3. Legal Proceedings",
                "The Company is a defendant in an action alleging patent "
                "infringement and seeking an injunction and damages. "
                "See Note 12 to the Consolidated Financial Statements for "
                "the related accrual. Management believes the action is "
                "without merit and intends to defend it vigorously.",
            ]
        )
    )
    assert emission is not None
    assert emission.disposition is LegalProceedingsDisposition.SUBSTANTIVE


def test_displaced_item_3_still_emits() -> None:
    emission, _, _ = _emit(
        [
            "Item 3. Legal Proceedings",
            "Legal prose describing a pending action in detail.",
            "Item 1. Business",
            "Business prose.",
            "Item 1A. Risk Factors",
            "Risk prose.",
        ]
    )
    assert emission is not None
    assert emission.start_line == 0
    assert emission.disposition is LegalProceedingsDisposition.SUBSTANTIVE


def test_document_without_item_3_emits_nothing() -> None:
    emission, _, _ = _emit(
        [
            "Item 1. Business",
            "Business prose.",
            "Item 2. Properties",
            "Properties prose.",
        ]
    )
    assert emission is None
