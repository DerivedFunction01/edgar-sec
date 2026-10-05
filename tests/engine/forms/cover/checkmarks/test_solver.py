"""Contract tests for constraint-based cover checkbox inference."""

from __future__ import annotations

from types import SimpleNamespace

from edgar_sec.domain.forms.families.annual.checkmarks import ANNUAL_CHECKBOX_SCHEMA
from edgar_sec.engine.forms.cover.checkmarks.candidates import extract_table_candidates
from edgar_sec.engine.forms.cover.checkmarks.models import (
    CheckboxCandidate,
    InferenceStatus,
    PenaltyScorer,
)
from edgar_sec.engine.forms.cover.checkmarks.solver import (
    canonical_semantic_key,
    infer_cover_checkmarks,
    solve_filer_constraints,
    solve_report_period,
    solve_statutory_constraints,
)
from edgar_sec.engine.forms.cover.models import BoundaryMethod, CoverBoundary


def _filer_candidates(glyphs: tuple[str, str, str, str, str]):
    keys = (
        "large_accelerated_filer",
        "accelerated_filer",
        "non_accelerated_filer",
        "smaller_reporting_company",
        "emerging_growth_company",
    )
    return tuple(
        CheckboxCandidate(key, glyph, "filer_status")
        for key, glyph in zip(keys, glyphs, strict=True)
    )


def _boundary(text: str) -> CoverBoundary:
    return CoverBoundary(
        end_line=len(text.splitlines()),
        end_offset=None,
        method=BoundaryMethod.STRUCTURAL,
        confidence=1.0,
        start_line=0,
    )


def test_filer_primary_triplet_allows_src_and_egc_together() -> None:
    result = solve_filer_constraints(_filer_candidates(("G0", "G1", "G0", "G1", "G1")))

    assert result.status is InferenceStatus.RESOLVED
    assert result.penalty == 0
    assert {decision.source_token: decision.state for decision in result.decisions} == {
        "G0": "unchecked",
        "G1": "checked",
    }


def test_filer_soft_penalty_selects_lowest_violation_hypothesis() -> None:
    result = solve_filer_constraints(_filer_candidates(("G0", "G1", "G1", "G0", "G1")))

    assert result.status is InferenceStatus.RESOLVED
    assert result.penalty is not None
    assert result.penalty > 0
    assert result.decisions
    assert any(item.startswith("soft_penalty_recovery") for item in result.diagnostics)


def test_penalty_weights_are_configurable_for_html_edge_cases() -> None:
    result = solve_filer_constraints(
        _filer_candidates(("G0", "G1", "G1", "G0", "G1")),
        scorer=PenaltyScorer(filer_laf_overlay=2000, primary_exactly_one=100),
    )

    assert result.status is InferenceStatus.RESOLVED
    assert result.penalty == 100


def test_homogeneous_primary_triplet_is_tied_and_preserved() -> None:
    result = solve_filer_constraints(_filer_candidates(("G0", "G0", "G0", "G1", "G1")))

    assert result.status is InferenceStatus.UNRESOLVED
    assert result.decisions == ()
    assert "hypotheses_tied" in result.diagnostics


def test_an_incomplete_filer_group_is_absent_not_unresolved() -> None:
    result = solve_filer_constraints(
        (CheckboxCandidate("large_accelerated_filer", "G0", "filer_status"),)
    )

    assert result.status is InferenceStatus.ABSENT
    assert "filer_group_incomplete" in result.diagnostics


def test_duplicate_semantic_rows_are_reported_as_unresolved() -> None:
    result = solve_filer_constraints(
        (
            CheckboxCandidate("large_accelerated_filer", "G0", "filer_status"),
            CheckboxCandidate("large_accelerated_filer", "G1", "filer_status"),
        )
    )

    assert result.status is InferenceStatus.UNRESOLVED
    assert any(
        item.startswith("duplicate_semantic_rows") for item in result.diagnostics
    )


def test_report_period_without_transition_date_selects_annual() -> None:
    result = solve_report_period(
        (
            CheckboxCandidate("annual", "G0", "report_period", date_valid=True),
            CheckboxCandidate("transition", "G1", "report_period", date_valid=False),
        ),
        family="10-K",
    )

    assert result.status is InferenceStatus.RESOLVED
    assert result.facts == (("selected_period", "annual"),)
    assert [(item.source_token, item.state) for item in result.decisions] == [
        ("G0", "checked"),
        ("G1", "unchecked"),
    ]


def test_report_period_for_a_family_without_a_schema_is_not_applicable() -> None:
    result = solve_report_period(
        (CheckboxCandidate("annual", "G0", "report_period"),), family="8-K"
    )

    assert result.status is InferenceStatus.NOT_APPLICABLE


def test_statutory_constraints_reject_wksi_shell_hypothesis() -> None:
    rows = (
        ("wksi", "G0", "yes"),
        ("wksi", "G1", "no"),
        ("shell_company", "G0", "yes"),
        ("shell_company", "G1", "no"),
        ("voluntary_filer", "G0", "yes"),
        ("voluntary_filer", "G1", "no"),
        ("compliant_12_months", "G1", "yes"),
        ("compliant_12_months", "G0", "no"),
        ("sox_404b", "G1", "yes"),
        ("sox_404b", "G0", "no"),
    )
    candidates = tuple(
        CheckboxCandidate(
            semantic_key,
            glyph,
            "statutory_binary",
            answer=answer,
            question_key=semantic_key,
        )
        for semantic_key, glyph, answer in rows
    )

    result = solve_statutory_constraints(candidates, schema=ANNUAL_CHECKBOX_SCHEMA)

    assert result.status is InferenceStatus.RESOLVED
    assert result.penalty == 0
    assert {decision.source_token: decision.state for decision in result.decisions} == {
        "G0": "unchecked",
        "G1": "checked",
    }


def test_same_glyph_on_yes_and_no_is_unresolved() -> None:
    result = solve_statutory_constraints(
        (
            CheckboxCandidate(
                "shell_company",
                "G0",
                "statutory_binary",
                answer="yes",
                question_key="shell_company",
            ),
            CheckboxCandidate(
                "shell_company",
                "G0",
                "statutory_binary",
                answer="no",
                question_key="shell_company",
            ),
        ),
        schema=ANNUAL_CHECKBOX_SCHEMA,
    )

    assert result.status is InferenceStatus.UNRESOLVED
    assert result.decisions == ()


def test_a_schema_without_a_statutory_group_is_not_applicable() -> None:
    result = solve_statutory_constraints(
        (CheckboxCandidate("annual", "G0", "report_period"),),
        schema=SimpleNamespace(groups=(), constraints=()),
    )

    assert result.status is InferenceStatus.NOT_APPLICABLE


def test_prose_decisions_report_that_text_changed() -> None:
    boundary = CoverBoundary(
        end_line=3,
        end_offset=None,
        method="phrase",
        confidence=1.0,
        start_line=0,
    )
    text = "FORM 10-K\nANNUAL REPORT ●\nTRANSITION REPORT o\n"
    result = infer_cover_checkmarks(text, boundary, family="10-K")

    assert result.status is InferenceStatus.RESOLVED
    assert result.decisions


def test_a_filing_with_no_candidates_is_absent() -> None:
    text = "FORM 10-K\nnothing checkable here\n"

    assert (
        infer_cover_checkmarks(text, _boundary(text), family="10-K").status
        is InferenceStatus.ABSENT
    )


def test_a_family_without_a_schema_is_not_applicable() -> None:
    text = "FORM 8-K\nItem 7.01 Regulation FD Disclosure\n"

    assert (
        infer_cover_checkmarks(text, _boundary(text), family="8-K").status
        is InferenceStatus.NOT_APPLICABLE
    )


def test_an_unknown_boundary_end_is_not_applicable() -> None:
    boundary = CoverBoundary(
        end_line=None,
        end_offset=None,
        method=BoundaryMethod.DISABLED,
        confidence=0.0,
    )

    assert (
        infer_cover_checkmarks("WKSI o Yes No", boundary, family="8-K").status
        is InferenceStatus.NOT_APPLICABLE
    )


def test_canonical_key_normalizes_separators_and_known_aliases() -> None:
    assert canonical_semantic_key("Non Accelerated Filer") == "non_accelerated_filer"
    assert canonical_semantic_key("wksi") == "well_known_seasoned_issuer"
    assert canonical_semantic_key("Shell Company") == "shell_company"
    assert canonical_semantic_key("unknown label") == "unknown label"


def test_table_geometry_drives_the_filer_solution() -> None:
    geometry = SimpleNamespace(
        rows=(
            ("●", "Large accelerated filer"),
            ("o", "Accelerated filer"),
            ("●", "Non-accelerated filer"),
            ("o", "Smaller reporting company"),
            ("o", "Emerging growth company"),
        )
    )

    result = solve_filer_constraints(extract_table_candidates(geometry, table_index=0))

    assert result.status is InferenceStatus.RESOLVED
    assert {candidate.semantic_key for candidate in result.candidates} == {
        "large_accelerated_filer",
        "accelerated_filer",
        "non_accelerated_filer",
        "smaller_reporting_company",
        "emerging_growth_company",
    }


def test_more_than_two_ambiguous_glyph_classes_is_unresolved() -> None:
    candidates = tuple(
        CheckboxCandidate(key, f"G{index}", "filer_status")
        for index, key in enumerate(
            (
                "large_accelerated_filer",
                "accelerated_filer",
                "non_accelerated_filer",
                "smaller_reporting_company",
                "emerging_growth_company",
            )
        )
    )

    result = solve_filer_constraints(candidates)

    assert result.status is InferenceStatus.UNRESOLVED
    assert "more_than_two_glyph_classes" in result.diagnostics
