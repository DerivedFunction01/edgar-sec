"""Contract tests for cover checkbox candidate extraction."""

from __future__ import annotations

from types import SimpleNamespace

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
