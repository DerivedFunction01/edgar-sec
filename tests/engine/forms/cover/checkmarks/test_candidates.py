"""Contract tests for cover checkbox candidate extraction."""

from __future__ import annotations

from types import SimpleNamespace

from edgar_sec.domain.forms.families.annual.checkmarks import ANNUAL_CHECKBOX_SCHEMA
from edgar_sec.domain.forms.families.quarterly.checkmarks import (
    QUARTERLY_CHECKBOX_SCHEMA,
)
from edgar_sec.engine.forms.cover.checkmarks.candidates import (
    extract_cover_candidates,
    extract_table_candidates,
)
from edgar_sec.engine.forms.cover.models import BoundaryMethod, CoverBoundary


def _boundary(text: str, end_line: int | None = None) -> CoverBoundary:
    return CoverBoundary(
        start_line=0,
        end_line=len(text.splitlines()) if end_line is None else end_line,
        end_offset=None,
        method=BoundaryMethod.STRUCTURAL,
        confidence=1.0,
    )


def test_a_variable_width_ascii_pair_yields_both_known_states() -> None:
    text = "FORM 10-K\nANNUAL REPORT [X]\nTRANSITION REPORT /   /\n"
    candidates = extract_cover_candidates(text, _boundary(text), family="10-K")

    assert {candidate.source_token for candidate in candidates} == {"[X]", "/   /"}
    assert {candidate.known_state for candidate in candidates} == {
        "checked",
        "unchecked",
    }


def test_report_period_labels_are_selected_by_family_schema() -> None:
    quarterly = "FORM 10-Q\nQUARTERLY REPORT [X]\nTRANSITION REPORT [ ]\n"
    annual_text = "FORM 10-K\nQUARTERLY REPORT [X]\n"
    current = "FORM 8-K\nANNUAL REPORT [X]\nTRANSITION REPORT [ ]\n"

    quarterly_candidates = extract_cover_candidates(
        quarterly, _boundary(quarterly), family="10-Q"
    )
    annual_candidates = extract_cover_candidates(
        annual_text, _boundary(annual_text), family="10-K"
    )
    current_candidates = extract_cover_candidates(
        current, _boundary(current), family="8-K"
    )

    assert {candidate.semantic_key for candidate in quarterly_candidates} == {
        "quarterly",
        "transition",
    }
    assert annual_candidates == ()
    assert current_candidates == ()


def test_form_6k_annual_report_options_use_the_6k_schema() -> None:
    text = "FORM 6-K\nForm 20-F [X]\nForm 40-F [ ]\n"
    candidates = extract_cover_candidates(text, _boundary(text), family="6-K")
    wrong_family = extract_cover_candidates(text, _boundary(text), family="8-K")

    assert [candidate.semantic_key for candidate in candidates] == [
        "annual_report_form_20f",
        "annual_report_form_40f",
    ]
    assert wrong_family == ()


def test_form_8k_simultaneous_filing_options_use_the_8k_schema() -> None:
    text = (
        "FORM 8-K\n"
        "Written communications pursuant to Rule 425 [X]\n"
        "Soliciting material pursuant to Rule 14a-12 [ ]\n"
        "Pre-commencement communications pursuant to Rule 14d-2(b) [ ]\n"
        "Pre-commencement communications pursuant to Rule 13e-4(c) [ ]\n"
    )
    candidates = extract_cover_candidates(text, _boundary(text), family="8-K")
    wrong_family = extract_cover_candidates(text, _boundary(text), family="6-K")

    assert [candidate.semantic_key for candidate in candidates] == [
        "written_communications_rule_425",
        "soliciting_material_rule_14a12",
        "precommencement_communications_rule_14d2b",
        "precommencement_communications_rule_13e4c",
    ]
    assert wrong_family == ()


def test_a_parenthesized_checked_mark_is_canonicalized() -> None:
    text = "FORM 10-K\nANNUAL REPORT (X )\nTRANSITION REPORT [ ]\n"
    candidates = extract_cover_candidates(text, _boundary(text), family="10-K")

    assert {candidate.source_token for candidate in candidates} == {"(X )", "[ ]"}
    assert {candidate.known_state for candidate in candidates} == {
        "checked",
        "unchecked",
    }


def test_a_braced_unchecked_mark_is_recognized_as_unchecked() -> None:
    text = "FORM 10-K\nANNUAL REPORT [X]\nTRANSITION REPORT { }\n"
    candidates = extract_cover_candidates(text, _boundary(text), family="10-K")

    transition = [
        candidate for candidate in candidates if candidate.semantic_key == "transition"
    ]
    assert len(transition) == 1
    assert transition[0].source_token == "{ }"
    assert transition[0].known_state == "unchecked"


def test_transition_period_date_blanks_are_not_report_marks() -> None:
    text = "FORM 10-K\nTRANSITION REPORT for the period from _________ to _________\n"
    candidates = extract_cover_candidates(text, _boundary(text), family="10-K")

    assert candidates == ()


def test_prose_asterisks_are_not_checkbox_candidates() -> None:
    text = "has filed all reports required *\npreceding 12 months *\nPART I\n"
    candidates = extract_cover_candidates(text, _boundary(text), family="10-K")

    assert candidates == ()


def test_an_unknown_boundary_end_yields_no_candidates() -> None:
    boundary = CoverBoundary(
        start_line=None,
        end_line=None,
        end_offset=None,
        method=BoundaryMethod.DISABLED,
        confidence=0.0,
    )

    assert extract_cover_candidates("FORM 10-K\n", boundary, family="10-K") == ()


def test_table_candidates_pair_each_filer_mark_with_its_nearest_label() -> None:
    geometry = SimpleNamespace(
        rows=(
            ("Large accelerated filer", "o", "", "Accelerated filer", "o"),
            (
                "Non-accelerated filer",
                "x",
                "(Do not check if a smaller reporting company)",
                "Smaller reporting company",
                "o",
            ),
        )
    )

    candidates = extract_table_candidates(geometry, table_index=0)

    assert [(candidate.semantic_key, candidate.column) for candidate in candidates] == [
        ("large_accelerated_filer", 1),
        ("accelerated_filer", 4),
        ("non_accelerated_filer", 1),
        ("smaller_reporting_company", 4),
    ]


def test_table_report_period_labels_come_from_selected_schema() -> None:
    annual_geometry = SimpleNamespace(
        rows=(("Annual report", "o"), ("Transition report", "o"))
    )
    quarterly_geometry = SimpleNamespace(
        rows=(("Quarterly report", "o"), ("Transition report", "o"))
    )

    annual = extract_table_candidates(
        annual_geometry, table_index=0, schema=ANNUAL_CHECKBOX_SCHEMA
    )
    quarterly = extract_table_candidates(
        quarterly_geometry, table_index=0, schema=QUARTERLY_CHECKBOX_SCHEMA
    )
    wrong_family = extract_table_candidates(
        quarterly_geometry, table_index=0, schema=ANNUAL_CHECKBOX_SCHEMA
    )

    assert [candidate.semantic_key for candidate in annual] == [
        "annual",
        "transition",
    ]
    assert [candidate.semantic_key for candidate in quarterly] == [
        "quarterly",
        "transition",
    ]
    assert {candidate.semantic_key for candidate in wrong_family} == {"transition"}


def test_table_candidates_support_above_label_orientation() -> None:
    geometry = SimpleNamespace(
        rows=(
            ("●",),
            ("Large accelerated filer",),
            ("o",),
            ("Accelerated filer",),
            ("●",),
            ("Non-accelerated filer",),
            ("o",),
            ("Smaller reporting company",),
            ("o",),
            ("Emerging growth company",),
        )
    )

    candidates = extract_table_candidates(geometry, table_index=0)

    assert {candidate.orientation for candidate in candidates} == {"above_label"}


def test_table_candidates_distinguish_left_and_right_marks_in_one_cell() -> None:
    geometry = SimpleNamespace(
        rows=(
            ("o Large accelerated filer",),
            ("Accelerated filer o",),
        )
    )

    candidates = extract_table_candidates(geometry, table_index=0)

    assert [candidate.orientation for candidate in candidates] == [
        "left_of_label",
        "right_of_label",
    ]


def test_table_candidates_distinguish_vertical_marks_in_one_cell() -> None:
    geometry = SimpleNamespace(
        rows=(
            ("o\nLarge accelerated filer",),
            ("Large accelerated filer\no",),
        )
    )

    candidates = extract_table_candidates(geometry, table_index=0)

    assert [candidate.orientation for candidate in candidates] == [
        "above_label",
        "below_label",
    ]


def test_line_candidates_distinguish_left_and_right_marks() -> None:
    text = "FORM 10-K\n[X] ANNUAL REPORT\nTRANSITION REPORT [ ]\n"

    candidates = extract_cover_candidates(text, _boundary(text), family="10-K")

    assert {
        candidate.semantic_key: candidate.orientation for candidate in candidates
    } == {
        "annual": "left_of_label",
        "transition": "right_of_label",
    }


def test_a_pure_yes_no_table_row_becomes_one_binary_question() -> None:
    geometry = SimpleNamespace(rows=(("", "o Yes", "x No"),))
    candidates = extract_table_candidates(geometry, table_index=0)

    assert [(candidate.answer, candidate.semantic_key) for candidate in candidates] == [
        ("yes", "table_yes_no:0:0"),
        ("no", "table_yes_no:0:0"),
    ]


def test_candidate_regions_name_the_line_and_mark_offset() -> None:
    text = "FORM 10-K\nANNUAL REPORT [X]\n"
    candidates = extract_cover_candidates(text, _boundary(text), family="10-K")

    assert candidates
    for candidate in candidates:
        assert candidate.source_region.startswith("line-")
        assert candidate.mark_span is not None
        assert text[candidate.mark_span[0] : candidate.mark_span[1]] == (
            candidate.source_token
        )


def test_a_label_in_parentheses_does_not_admit_a_cell_mark() -> None:
    geometry = SimpleNamespace(rows=(("(Do not check)", "o"),))
    candidates = extract_table_candidates(geometry, table_index=0)

    assert candidates == ()


def test_multi_spaced_cover_labels_are_recognized() -> None:
    text = "FORM 10-K\nANNUAL  REPORT [X]\nTRANSITION  REPORT /  /\n"
    candidates = extract_cover_candidates(text, _boundary(text), family="10-K")

    assert {candidate.semantic_key for candidate in candidates} == {
        "annual",
        "transition",
    }
    assert {candidate.source_token for candidate in candidates} == {"[X]", "/  /"}
    assert {candidate.known_state for candidate in candidates} == {
        "checked",
        "unchecked",
    }


def test_hyphenated_filer_labels_distinguish_non_accelerated_from_accelerated() -> None:
    text = "FORM 10-K\nNon - accelerated filer [X]\nAccelerated filer [ ]\n"
    candidates = extract_cover_candidates(text, _boundary(text), family="10-K")

    keys = [candidate.semantic_key for candidate in candidates]
    assert keys == ["non_accelerated_filer", "accelerated_filer"]


def test_wide_columnar_whitespace_does_not_bridge_separate_labels() -> None:
    text = "FORM 10-K\nAnnual          Report of Condition [X]\n"
    candidates = extract_cover_candidates(text, _boundary(text), family="10-K")

    # Wide 10-space column gap prevents "Annual ... Report" from matching as "annual report"
    assert not any(c.semantic_key == "annual" for c in candidates)


def test_slash_wrapped_report_marks_abutting_words_are_extracted() -> None:
    text = (
        "FORM 10-K\n"
        "/ x /Annual  Report  Pursuant  to  Section  13 or 15 (d)\n"
        "or /  /Transition  report  pursuant  to  section  13 or 15(d)\n"
    )
    candidates = extract_cover_candidates(text, _boundary(text), family="10-K")

    by_key = {c.semantic_key: c for c in candidates}
    assert "annual" in by_key
    assert "transition" in by_key
    assert by_key["annual"].source_token == "/ x /"
    assert by_key["annual"].known_state == "checked"
    assert by_key["transition"].source_token == "/  /"
    assert by_key["transition"].known_state == "unchecked"


def test_plural_report_labels_are_extracted() -> None:
    text = (
        "FORM 10-K\n"
        "ý ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d)\n"
        "o TRANSITION REPORTS PURSUANT TO SECTION 13 OR 15(d)\n"
    )
    candidates = extract_cover_candidates(text, _boundary(text), family="10-K")

    by_key = {c.semantic_key: c for c in candidates}
    assert "annual" in by_key
    assert "transition" in by_key
    assert by_key["annual"].source_token == "ý"
    assert by_key["transition"].source_token == "o"
