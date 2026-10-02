"""Run validation, conservative healing, and alternating-run unification."""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.page_markers.models import PageCandidate
from edgar_sec.engine.document.page_markers.sequence import (
    MAX_INTERPOLATED_GAP,
    heal_run,
    monotone_fraction,
    unify_alternating_runs,
    validate_group,
)


def _candidate(
    value: int, line: int, *, family: str = "bare_number", namespace: str = "arabic"
) -> PageCandidate:
    return PageCandidate(
        start=line * 10,
        end=line * 10 + 1,
        start_line=line,
        end_line=line,
        text=str(value),
        family=family,
        namespace=namespace,
        value=value,
    )


def _run(
    values: tuple[int, ...],
    *,
    stride: int = 4,
    strategy: str = "test",
    min_members: int = 3,
    min_monotone: float = 0.8,
):
    candidates = tuple(
        _candidate(value, index * stride) for index, value in enumerate(values)
    )
    run = validate_group(
        candidates,
        strategy=strategy,
        min_members=min_members,
        min_monotone=min_monotone,
    )
    assert run is not None
    return run


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([], 0.0),
        ([1], 0.0),
        ([1, 2, 3, 4], 1.0),
        ([1, 2, 2, 3], 2 / 3),
        ([5, 4, 3], 0.0),
        ([1, 2, 30, 4], 1 / 3),
    ],
)
def test_monotone_fraction_counts_bounded_increases_only(
    values: list[int], expected: float
) -> None:
    assert monotone_fraction(values) == pytest.approx(expected)


def test_monotone_fraction_bounds_the_step_it_accepts() -> None:
    assert monotone_fraction([1, 2, 3, 4], max_delta=2) == 1.0
    assert monotone_fraction([1, 4, 7], max_delta=2) == 0.0


def test_a_group_below_the_member_floor_is_not_a_run() -> None:
    assert validate_group([_candidate(1, 0), _candidate(2, 4)], strategy="t") is None


def test_a_group_below_the_gap_floor_is_not_a_run() -> None:
    dense = [_candidate(index, index * 2) for index in range(1, 6)]
    assert validate_group(dense, strategy="t", min_gap_median=8) is None


def test_a_monotone_well_spaced_group_validates_with_its_statistics() -> None:
    run = _run((1, 2, 3, 4, 5), strategy="anchor_relative")
    assert run.family == "bare_number"
    assert run.namespace == "arabic"
    assert run.strategy == "anchor_relative"
    assert run.gap_median == 4.0
    assert run.gap_mean == 4.0
    assert run.alignment_fraction == 1.0
    assert run.monotone_fraction == 1.0
    assert (run.source_start_line, run.source_end_line) == (0, 16)


def test_healing_infers_a_gap_and_names_the_reason() -> None:
    run = _run((1, 2, 3, 6, 7))
    _healed, inferred, _promoted = heal_run(run)
    assert [item.page_number for item in inferred] == [4, 5]
    assert {item.reason for item in inferred} == {"interpolated_gap"}
    assert all(item.namespace == "arabic" for item in inferred)


def test_a_gap_at_the_interpolation_bound_is_still_inferred() -> None:
    run = _run((1, MAX_INTERPOLATED_GAP + 2), min_members=2, min_monotone=0.0)
    _healed, inferred, _promoted = heal_run(run)
    assert len(inferred) == MAX_INTERPOLATED_GAP


def test_a_gap_beyond_the_interpolation_bound_is_refused() -> None:
    run = _run((1, MAX_INTERPOLATED_GAP + 3), min_members=2, min_monotone=0.0)
    _healed, inferred, _promoted = heal_run(run)
    assert inferred == ()


def test_breaks_corroborating_a_gap_are_required_when_supplied() -> None:
    run = _run((1, 2, 3, 6, 7), stride=4)
    # Members 3 and 6 sit on lines 8 and 12; two breaks strictly between them
    # match the two missing values exactly.
    _healed, inferred, _promoted = heal_run(run, page_break_lines={9, 10})
    assert [item.reason for item in inferred] == [
        "validated_page_break_count",
        "validated_page_break_count",
    ]


def test_too_few_breaks_for_the_gap_refuses_the_inference() -> None:
    run = _run((1, 2, 3, 6, 7), stride=4)
    _healed, inferred, _promoted = heal_run(run, page_break_lines={9})
    assert inferred == ()


def test_more_breaks_than_missing_values_is_weaker_evidence() -> None:
    run = _run((1, 2, 3, 6, 7), stride=4)
    _healed, inferred, _promoted = heal_run(run, page_break_lines={9, 10, 11})
    assert {item.reason for item in inferred} == {"page_break_supported"}


def test_a_stronger_run_value_is_never_re_inferred() -> None:
    run = _run((1, 2, 6, 7), min_monotone=0.0)
    _healed, inferred, _promoted = heal_run(run, stronger_values={3, 4, 5})
    assert inferred == ()


def test_a_healed_run_reports_the_healing_in_its_strategy() -> None:
    healed, _inferred, _promoted = heal_run(_run((1, 2, 3, 6, 7)))
    assert healed.strategy == "test:healed"


def test_complementary_verso_recto_runs_unify() -> None:
    odds = validate_group(
        [
            _candidate(value, index * 4, family="bare_number")
            for index, value in enumerate((1, 3, 5, 7))
        ],
        strategy="odd",
    )
    evens = validate_group(
        [
            _candidate(value, index * 4 + 2, family="bare_number")
            for index, value in enumerate((2, 4, 6, 8))
        ],
        strategy="even",
    )
    assert odds is not None and evens is not None
    unified = unify_alternating_runs([odds, evens])
    assert len(unified) == 1
    assert unified[0].strategy == "alternating_verso_recto:odd"
    assert [item.value for item in unified[0].candidates] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_a_single_run_is_returned_untouched() -> None:
    run = _run((1, 2, 3, 4))
    assert unify_alternating_runs([run]) == [run]
    assert unify_alternating_runs([]) == []


def test_runs_in_different_namespaces_do_not_unify() -> None:
    arabic = validate_group(
        [_candidate(value, index * 4) for index, value in enumerate((1, 3, 5, 7))],
        strategy="odd",
    )
    roman = validate_group(
        [
            _candidate(value, index * 4 + 2, namespace="roman")
            for index, value in enumerate((2, 4, 6, 8))
        ],
        strategy="even",
    )
    assert arabic is not None and roman is not None
    assert len(unify_alternating_runs([arabic, roman])) == 2


def test_promotion_joins_a_compatible_candidate_into_its_gap() -> None:
    run = _run((1, 3, 5))
    gap = _candidate(2, 2)
    healed, inferred, promoted = heal_run(run, [gap])
    assert [item.value for item in promoted] == [2]
    assert [item.value for item in healed.candidates] == [1, 2, 3, 5]
    assert [item.page_number for item in inferred] == [4]
