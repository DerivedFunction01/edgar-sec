from types import SimpleNamespace

from defs.sec_forms.cover import (
    CheckboxCandidate,
    CoverBoundary,
    InferenceStatus,
    PenaltyScorer,
    apply_cover_checkmark_decisions,
    extract_cover_candidates,
    extract_table_candidates,
    infer_cover_checkmarks,
    solve_filer_constraints,
    solve_report_period,
    solve_statutory_constraints,
)
from defs.taxonomy.components.cover import ANNUAL_CHECKBOX_SCHEMA


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
    updated, changed = apply_cover_checkmark_decisions(text, result)

    assert changed
    assert "ANNUAL REPORT [X]" in updated
    assert "TRANSITION REPORT [ ]" in updated


def test_wingdings_unchecked_glyph_is_a_shared_cover_mark() -> None:
    boundary = CoverBoundary(
        end_line=2,
        end_offset=None,
        method="test",
        confidence=1.0,
        start_line=0,
    )
    candidates = extract_cover_candidates(
        "ANNUAL REPORT x\nTRANSITION REPORT ¨\n", boundary, family="10-K"
    )

    transition = [
        candidate for candidate in candidates if candidate.semantic_key == "transition"
    ]

    assert len(transition) == 1
    assert transition[0].known_state == "unchecked"


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


def test_table_candidates_use_left_right_geometry_and_apply_decisions() -> None:
    geometry = SimpleNamespace(
        rows=(
            ("●", "Large accelerated filer"),
            ("o", "Accelerated filer"),
            ("●", "Non-accelerated filer"),
            ("o", "Smaller reporting company"),
            ("o", "Emerging growth company"),
        )
    )
    candidates = extract_table_candidates(geometry, table_index=0)
    result = solve_filer_constraints(candidates)
    text = (
        "<TABLE>\n"
        + "\n".join(
            f"{glyph} | {label}"
            for glyph, label in zip(
                ("●", "o", "●", "o", "o"),
                (
                    "Large accelerated filer",
                    "Accelerated filer",
                    "Non-accelerated filer",
                    "Smaller reporting company",
                    "Emerging growth company",
                ),
                strict=True,
            )
        )
        + "\n</TABLE>"
    )
    updated, changed = apply_cover_checkmark_decisions(text, result)

    assert changed
    assert "[ ] | Large accelerated filer" in updated
    assert "[X] | Accelerated filer" in updated
    assert "[X] | Smaller reporting company" in updated


def test_table_candidates_pair_each_filer_mark_with_nearest_label() -> None:
    geometry = SimpleNamespace(
        rows=(
            (
                "Large accelerated filer",
                "o",
                "",
                "Accelerated filer",
                "o",
            ),
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


def test_pure_yes_no_table_is_inferred_and_unwrapped() -> None:
    geometry = SimpleNamespace(rows=(("", "o Yes", "x No"),))
    candidates = extract_table_candidates(geometry, table_index=0)

    result = solve_statutory_constraints(candidates, schema=ANNUAL_CHECKBOX_SCHEMA)
    updated, changed = apply_cover_checkmark_decisions(
        "<TABLE>\no Yes  [X] No\n</TABLE>", result
    )

    assert result.status is InferenceStatus.RESOLVED
    assert [(candidate.answer, candidate.semantic_key) for candidate in candidates] == [
        ("yes", "table_yes_no:0:0"),
        ("no", "table_yes_no:0:0"),
    ]
    assert changed
    assert updated == "[ ] Yes  [X] No"


def test_prose_asterisks_are_not_checkbox_candidates() -> None:
    text = "has filed all reports required *\npreceding 12 months *\nPART I\n"
    boundary = CoverBoundary(
        end_line=3,
        end_offset=None,
        method="test",
        confidence=1.0,
        start_line=0,
    )

    candidates = extract_cover_candidates(text, boundary, family="10-K")

    assert candidates == ()


def test_table_candidates_support_above_below_orientation() -> None:
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
    result = solve_filer_constraints(candidates)

    assert result.status is InferenceStatus.RESOLVED
    assert result.penalty == 0
    assert {candidate.orientation for candidate in candidates} == {"above_label"}


def test_no_cover_profiles_do_not_infer_checkbox_states() -> None:
    from defs.sec_forms.cover import infer_cover_checkmarks

    boundary = CoverBoundary(
        end_line=4,
        end_offset=10,
        method="unknown",
        confidence=0.0,
    )
    result = infer_cover_checkmarks("WKSI o Yes No", boundary, family="8-K")

    assert result.status is InferenceStatus.NOT_APPLICABLE
