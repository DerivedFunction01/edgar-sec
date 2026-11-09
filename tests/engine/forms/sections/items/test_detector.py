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


def _labels(seq) -> list[str]:
    return [s.item_identifier for s in seq.sections]


def test_swap_keeps_both_items_and_marks_the_displaced_one() -> None:
    text = "\n".join(
        [
            "Item 1. Business",
            "Business prose.",
            "Item 2. Properties",
            "Properties prose.",
            "Item 1A. Risk Factors",
            "Risk prose.",
            "Item 3. Legal Proceedings",
            "Legal prose.",
        ]
    )
    seq = detect_section_sequence(text, family="10-K", taxonomy_items=FORM_10K_ITEMS)
    assert _labels(seq) == ["ITEM 1", "ITEM 2", "ITEM 1A", "ITEM 3"]
    by_label = {s.item_identifier: s for s in seq.sections}
    assert by_label["ITEM 1A"].displaced is True
    assert by_label["ITEM 1"].displaced is False
    assert by_label["ITEM 2"].displaced is False
    assert seq.disordered is False
    assert seq.anachronistic_rejections == 0
    assert "ITEM 1A" not in seq.missing_items


def test_displaced_item_bound_at_document_start() -> None:
    text = "\n".join(
        [
            "Item 3. Legal Proceedings",
            "Legal prose.",
            "Item 1. Business",
            "Business prose.",
            "Item 1A. Risk Factors",
            "Risk prose.",
        ]
    )
    seq = detect_section_sequence(text, family="10-K", taxonomy_items=FORM_10K_ITEMS)
    assert _labels(seq) == ["ITEM 3", "ITEM 1", "ITEM 1A"]
    first = seq.sections[0]
    assert first.displaced is True
    assert (first.start_line, first.end_line) == (0, 1)


def test_displaced_item_at_document_end_spans_to_last_line() -> None:
    text = "\n".join(
        [
            "Item 1. Business",
            "Business prose.",
            "Item 3. Legal Proceedings",
            "Legal prose.",
            "Item 2. Properties",
            "Properties prose.",
        ]
    )
    seq = detect_section_sequence(text, family="10-K", taxonomy_items=FORM_10K_ITEMS)
    assert _labels(seq) == ["ITEM 1", "ITEM 3", "ITEM 2"]
    last = seq.sections[-1]
    assert last.item_identifier == "ITEM 2"
    assert last.displaced is True
    assert last.end_line == 6


def test_displaced_item_with_an_empty_span() -> None:
    text = "\n".join(
        [
            "Item 2. Properties",
            "Item 1. Business",
            "Business prose.",
            "Item 1A. Risk Factors",
            "Risk prose.",
        ]
    )
    seq = detect_section_sequence(text, family="10-K", taxonomy_items=FORM_10K_ITEMS)
    assert _labels(seq) == ["ITEM 2", "ITEM 1", "ITEM 1A"]
    displaced = seq.sections[0]
    assert displaced.displaced is True
    assert displaced.start_line == displaced.end_line == 0


def test_two_independent_swaps_in_one_document() -> None:
    text = "\n".join(
        [
            "Item 1A. Risk Factors",
            "Risk prose.",
            "Item 1. Business",
            "Business prose.",
            "Item 3. Legal Proceedings",
            "Legal prose.",
            "Item 2. Properties",
            "Properties prose.",
        ]
    )
    seq = detect_section_sequence(text, family="10-K", taxonomy_items=FORM_10K_ITEMS)
    assert _labels(seq) == ["ITEM 1A", "ITEM 1", "ITEM 3", "ITEM 2"]
    assert sum(1 for s in seq.sections if s.displaced) == 2
    assert seq.disordered is False


def test_globally_disordered_stream_falls_back_to_first_fit() -> None:
    text = "\n".join(
        [
            "Item 3. Legal Proceedings",
            "Legal prose.",
            "Item 2. Properties",
            "Properties prose.",
            "Item 1. Business",
            "Business prose.",
        ]
    )
    seq = detect_section_sequence(text, family="10-K", taxonomy_items=FORM_10K_ITEMS)
    assert _labels(seq) == ["ITEM 3"]
    assert seq.disordered is True
    assert seq.anachronistic_rejections == 2


def test_duplicate_heading_is_rejected_not_displaced() -> None:
    text = "\n".join(
        [
            "Item 1. Business",
            "Business prose.",
            "Item 2. Properties",
            "Properties prose.",
            "Item 2. Properties",
            "Repeated heading prose.",
            "Item 3. Legal Proceedings",
            "Legal prose.",
        ]
    )
    seq = detect_section_sequence(text, family="10-K", taxonomy_items=FORM_10K_ITEMS)
    assert _labels(seq) == ["ITEM 1", "ITEM 2", "ITEM 3"]
    assert all(not s.displaced for s in seq.sections)
    assert seq.anachronistic_rejections == 1


def test_toc_span_heading_is_not_readmitted_as_displaced() -> None:
    lines = [
        "Contents",
        "Item 2. Properties .... 5",
        "Item 1. Business .... 3",
        "Item 1. Business",
        "Business prose.",
        "Item 1A. Risk Factors",
        "Risk prose.",
        "Item 2. Properties",
        "Properties prose.",
    ]
    seq = detect_section_sequence(
        "\n".join(lines),
        family="10-K",
        taxonomy_items=FORM_10K_ITEMS,
        toc_span=(0, 2),
    )
    assert _labels(seq) == ["ITEM 1", "ITEM 1A", "ITEM 2"]
    assert seq.sections[-1].start_line == 7
    assert all(not s.displaced for s in seq.sections)


def test_continuation_flagged_candidate_is_not_readmitted() -> None:
    text = "\n".join(
        [
            "Item 1. Business",
            "Business prose.",
            "Item 2. Properties",
            "The legal proceedings are described in:",
            "Item 3.",
            "Item 4. Mine Safety Disclosures",
            "Safety prose.",
        ]
    )
    seq = detect_section_sequence(text, family="10-K", taxonomy_items=FORM_10K_ITEMS)
    assert "ITEM 3" not in _labels(seq)


def test_body_slice_detection_unaffected_by_a_displaced_cover_heading() -> None:
    lines = [
        "Item 3. Legal Proceedings",
        "Item 1. Business",
        "Business prose.",
        "Item 1A. Risk Factors",
        "Risk prose.",
    ]
    full = detect_section_sequence(
        "\n".join(lines), family="10-K", taxonomy_items=FORM_10K_ITEMS
    )
    assert _labels(full) == ["ITEM 3", "ITEM 1", "ITEM 1A"]
    body = detect_section_sequence(
        "\n".join(lines[1:]), family="10-K", taxonomy_items=FORM_10K_ITEMS
    )
    assert _labels(body) == ["ITEM 1", "ITEM 1A"]
    assert all(not s.displaced for s in body.sections)
    assert body.disordered is False


def test_empty_and_singleton_documents() -> None:
    empty = detect_section_sequence("", family="10-K", taxonomy_items=FORM_10K_ITEMS)
    assert empty.sections == ()
    assert empty.disordered is False
    single = detect_section_sequence(
        "Item 2. Properties\nProperties prose.",
        family="10-K",
        taxonomy_items=FORM_10K_ITEMS,
    )
    assert _labels(single) == ["ITEM 2"]
    assert single.sections[0].displaced is False
    assert single.disordered is False


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


def test_detect_6_k_press_release_item_from_census_exemplars() -> None:
    from edgar_sec.domain.forms.families.current.taxonomy import FORM_6K_ITEMS
    from tests.support import fixture_path

    for name in (
        "sixk_press_release_0000912282-05-000713.txt",
        "sixk_press_release_0000899797-02-000224.txt",
    ):
        text = fixture_path(name).read_text(encoding="utf-8")
        seq = detect_section_sequence(text, family="6-K", taxonomy_items=FORM_6K_ITEMS)
        assert [s.item_identifier for s in seq.sections] == ["ITEM PRESS RELEASE"]


def test_6_k_text_without_press_release_names_no_item() -> None:
    from edgar_sec.domain.forms.families.current.taxonomy import FORM_6K_ITEMS

    text = "Report of foreign private issuer.\nThe registrant furnished a report.\n"
    seq = detect_section_sequence(text, family="6-K", taxonomy_items=FORM_6K_ITEMS)
    assert seq.sections == ()


def _statement_taxonomy():
    from edgar_sec.domain.forms.common.models import ItemDefinition

    def item(name: str) -> ItemDefinition:
        return ItemDefinition(
            item=f"ITEM {name.upper()}", part=1, names=(name,), optional=True
        )

    return (
        item("alpha report"),
        item("beta statement"),
        item("gamma statement"),
        item("omega report"),
    )


def test_disordered_stream_keeps_the_canonical_spine() -> None:
    text = "\n".join(
        [
            "Omega Report",
            "The omega report opens this filing body here.",
            "Beta Statement",
            "Beta figures follow in this statement section here.",
            "Gamma Statement",
            "Gamma figures follow in this statement section here.",
            "Alpha Report",
            "The alpha report closes the filing body here.",
        ]
    )
    seq = detect_section_sequence(
        text, family="TEST", taxonomy_items=_statement_taxonomy()
    )
    assert _labels(seq) == ["ITEM BETA STATEMENT", "ITEM GAMMA STATEMENT"]
    assert seq.disordered is True
    assert seq.anachronistic_rejections == 2


def test_dense_face_captions_without_later_recurrence_are_kept() -> None:
    text = "\n".join(
        [
            "1. Alpha report:",
            "",
            "2. Beta statement:",
            "",
            "3. Gamma statement:",
            "",
            "Body text follows here.",
        ]
    )
    seq = detect_section_sequence(
        text, family="TEST", taxonomy_items=_statement_taxonomy()
    )
    assert _labels(seq) == [
        "ITEM ALPHA REPORT",
        "ITEM BETA STATEMENT",
        "ITEM GAMMA STATEMENT",
    ]
