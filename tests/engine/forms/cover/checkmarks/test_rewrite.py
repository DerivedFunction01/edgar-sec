"""Contract tests for applying cover checkbox decisions to text and metadata."""

from __future__ import annotations

from types import SimpleNamespace

from edgar_sec.domain.forms.families.annual.checkmarks import ANNUAL_CHECKBOX_SCHEMA
from edgar_sec.engine.forms.cover.checkmarks.candidates import extract_table_candidates
from edgar_sec.engine.forms.cover.checkmarks.models import (
    CheckboxCandidate,
    CoverCheckmarkResult,
    InferenceStatus,
)
from edgar_sec.engine.forms.cover.checkmarks.rewrite import (
    apply_cover_checkmark_decisions,
    has_labeled_checkmark_candidates,
    has_resolvable_line_yes_no_candidates,
    update_table_geometries,
)
from edgar_sec.engine.forms.cover.checkmarks.solver import (
    infer_cover_checkmarks,
    solve_filer_constraints,
    solve_statutory_constraints,
)
from edgar_sec.engine.forms.cover.models import BoundaryMethod, CoverBoundary
from edgar_sec.engine.tables.ascii_html.converter import convert_html_table
from edgar_sec.engine.tables.ascii_html.model import TableGeometry


def _boundary(text: str) -> CoverBoundary:
    return CoverBoundary(
        end_line=len(text.splitlines()),
        end_offset=None,
        method=BoundaryMethod.STRUCTURAL,
        confidence=1.0,
        start_line=0,
    )


def test_a_result_with_nothing_to_do_is_left_alone() -> None:
    text = "FORM 10-K\nPART I\n"

    updated, changed, unwrapped = apply_cover_checkmark_decisions(
        text, CoverCheckmarkResult(status=InferenceStatus.ABSENT)
    )

    assert (updated, changed, unwrapped) == (text, False, frozenset())


def test_a_marked_yes_no_line_is_canonicalized() -> None:
    text = "[X] Yes No____; Yes____ No /X/\n"

    updated, changed, _ = apply_cover_checkmark_decisions(
        text,
        CoverCheckmarkResult(status=InferenceStatus.ABSENT),
    )

    assert changed
    assert updated == "[X] Yes No [ ]; Yes [ ] No [X]\n"


def test_an_incomplete_pair_does_not_block_a_complete_pair() -> None:
    text = "(1) Yes X No             (2) Yes X No___\n"

    updated, changed, _ = apply_cover_checkmark_decisions(
        text,
        CoverCheckmarkResult(status=InferenceStatus.ABSENT),
    )

    assert changed
    assert updated == "(1) Yes X No             (2) Yes [X] No [ ]\n"


def test_a_resolved_solution_rewrites_the_cover_text() -> None:
    text = "FORM 10-K\nANNUAL REPORT [X]\nTRANSITION REPORT /   /\n"
    result = infer_cover_checkmarks(text, _boundary(text), family="10-K")

    updated, changed, _ = apply_cover_checkmark_decisions(text, result)

    assert changed
    assert "ANNUAL REPORT [X]" in updated
    assert "TRANSITION REPORT [ ]" in updated


def test_a_repeated_underscore_checked_mark_is_one_token() -> None:
    text = "FORM 10-K\nYes _X__ No ___\n"
    result = infer_cover_checkmarks(text, _boundary(text), family="10-K")

    updated, changed, _ = apply_cover_checkmark_decisions(text, result)

    assert changed
    assert "Yes [X] No [ ]" in updated
    assert "[X][ ]" not in updated


def test_an_asymmetric_trailing_underscore_belongs_to_the_checked_mark() -> None:
    text = "FORM 10-KSB\nYes __ No X_\n"
    result = infer_cover_checkmarks(text, _boundary(text), family="10-KSB")

    updated, changed, _ = apply_cover_checkmark_decisions(text, result)

    assert changed
    assert "Yes [ ] No [X]" in updated
    assert "[X][ ]" not in updated


def test_a_dash_underline_is_removed_after_an_explicit_mark() -> None:
    text = "FORM 10-K\nYes [X] No\n---      ---\n"
    result = infer_cover_checkmarks(text, _boundary(text), family="10-K")

    updated, changed, _ = apply_cover_checkmark_decisions(text, result)

    assert changed
    assert "---" not in updated
    assert "Yes [X] No" in updated


def test_an_unmarked_dash_layout_is_preserved() -> None:
    text = "FORM 10-K\nYes No\n---  ---\n"
    result = infer_cover_checkmarks(text, _boundary(text), family="10-K")

    updated, _, _ = apply_cover_checkmark_decisions(text, result)

    assert "---  ---" in updated


def test_filer_grid_underscores_are_scoped_to_their_labels() -> None:
    text = (
        "FORM 10-K\n"
        "Non-accelerated filer___X__ Smaller reporting company___\n"
        "January __, 1998\n"
    )
    result = infer_cover_checkmarks(text, _boundary(text), family="10-K")

    updated, _, _ = apply_cover_checkmark_decisions(text, result)

    assert "Non-accelerated filer [X] Smaller reporting company [ ]" in updated
    assert "January __, 1998" in updated


def test_several_labels_sharing_one_mark_rewrite_it_once() -> None:
    """Re-applying the same mark span would slice the expanded canonical token
    into ``[X]X]X]...`` fragments where one Wingdings ``x`` served every label.
    """
    head = "Indicate by check mark if disclosure of delinquent filers is not contained herein. "
    tail = "\n\nIndicate by check mark whether the registrant is a shell company. "
    text = f"{head}x{tail}x Yes\n"
    delinquent_start = len(head)
    shell_start = len(head) + 1 + len(tail)
    filer_labels = (
        "large_accelerated_filer",
        "accelerated_filer",
        "non_accelerated_filer",
        "smaller_reporting_company",
    )
    candidates = (
        *(
            CheckboxCandidate(
                key,
                "x",
                "filer_status",
                source_region="line-0-mark-0",
                mark_span=(delinquent_start, delinquent_start + 1),
            )
            for key in filer_labels
        ),
        CheckboxCandidate(
            "shell_company",
            "x",
            "statutory",
            source_region="line-1-mark-0",
            mark_span=(shell_start, shell_start + 1),
        ),
    )
    result = CoverCheckmarkResult(
        status=InferenceStatus.RESOLVED, candidates=candidates
    )

    updated, changed, _ = apply_cover_checkmark_decisions(text, result)

    assert changed
    assert updated == f"{head}[X]{tail}[X] Yes\n"


def test_a_pure_yes_no_table_is_unwrapped_and_reported() -> None:
    geometry = SimpleNamespace(rows=(("", "o Yes", "x No"),))
    candidates = extract_table_candidates(geometry, table_index=0)

    result = solve_statutory_constraints(candidates, schema=ANNUAL_CHECKBOX_SCHEMA)
    updated, changed, unwrapped = apply_cover_checkmark_decisions(
        "<TABLE>\no Yes  [X] No\n</TABLE>", result
    )

    assert result.status is InferenceStatus.RESOLVED
    assert changed
    assert updated == "[ ] Yes  [X] No"
    assert unwrapped == frozenset({0})


def test_labeled_candidate_predicates_read_the_candidate_states() -> None:
    assert has_labeled_checkmark_candidates(()) is False
    assert has_labeled_checkmark_candidates(
        (CheckboxCandidate("annual", "[X]", "report_period"),)
    )
    assert (
        has_labeled_checkmark_candidates(
            (CheckboxCandidate("annual", "G0", "report_period"),)
        )
        is False
    )


def test_line_pair_predicate_requires_both_answers_and_known_states() -> None:
    assert has_resolvable_line_yes_no_candidates(()) is False
    assert (
        has_resolvable_line_yes_no_candidates(
            (
                CheckboxCandidate(
                    "table_yes_no:0:0",
                    "[X]",
                    "statutory_binary",
                    answer="yes",
                    question_key="table_yes_no:0:0",
                    state="checked",
                ),
                CheckboxCandidate(
                    "table_yes_no:0:0",
                    "[ ]",
                    "statutory_binary",
                    answer="no",
                    question_key="table_yes_no:0:0",
                    state="unchecked",
                ),
            )
        )
        is False
    )
    assert has_resolvable_line_yes_no_candidates(
        (
            CheckboxCandidate(
                "line_yes_no:1:0",
                "[X]",
                "statutory_binary",
                answer="yes",
                question_key="line_yes_no:1:0",
                state="checked",
            ),
            CheckboxCandidate(
                "line_yes_no:1:0",
                "[ ]",
                "statutory_binary",
                answer="no",
                question_key="line_yes_no:1:0",
                state="unchecked",
            ),
        )
    )


def test_update_table_geometries_evicts_unwrapped_tables() -> None:
    render = convert_html_table(
        "<table><tr><td>o</td><td>Yes</td></tr><tr><td>x</td><td>No</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=render)

    assert (
        update_table_geometries(
            (geometry,),
            CoverCheckmarkResult(status=InferenceStatus.ABSENT),
            frozenset({0}),
        )
        == ()
    )


def test_update_table_geometries_rewrites_the_matched_cell() -> None:
    result = solve_filer_constraints(
        extract_table_candidates(
            SimpleNamespace(
                rows=(
                    ("o", "Large accelerated filer"),
                    ("x", "Accelerated filer"),
                    ("o", "Non-accelerated filer"),
                    ("o", "Smaller reporting company"),
                    ("o", "Emerging growth company"),
                )
            ),
            table_index=0,
        )
    )
    render = convert_html_table(
        "<table><tr><td>o</td><td>Large accelerated filer</td></tr>"
        "<tr><td>x</td><td>Accelerated filer</td></tr>"
        "<tr><td>o</td><td>Non-accelerated filer</td></tr>"
        "<tr><td>o</td><td>Smaller reporting company</td></tr>"
        "<tr><td>o</td><td>Emerging growth company</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=render)

    updated = update_table_geometries((geometry,), result)

    assert len(updated) == 1
    assert updated[0].table_index == 0


def test_update_table_geometries_passes_through_without_candidates() -> None:
    render = convert_html_table("<table><tr><td>plain</td></tr></table>")
    geometry = TableGeometry(table_index=3, render_result=render)

    assert update_table_geometries(
        (geometry,), CoverCheckmarkResult(status=InferenceStatus.ABSENT)
    ) == (geometry,)
