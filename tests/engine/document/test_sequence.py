"""Unit tests for edgar_sec.engine.document.sequence."""

from __future__ import annotations

from edgar_sec.engine.document.page_markers import PageCandidate
from edgar_sec.engine.document.sequence import (
    heal_run,
    monotone_fraction,
    unify_alternating_runs,
    validate_group,
)


def _candidate(line: int, val: int, ns: str = "main") -> PageCandidate:
    return PageCandidate(
        start=line * 80,
        end=line * 80 + 5,
        start_line=line,
        end_line=line + 1,
        text=str(val),
        family="page_number",
        namespace=ns,
        value=val,
    )


def test_monotone_fraction() -> None:
    assert monotone_fraction([1, 2, 3, 4]) == 1.0
    assert monotone_fraction([1, 2, 5, 6], max_delta=3) == 1.0
    assert monotone_fraction([1, 5, 2], max_delta=3) == 0.0
    assert monotone_fraction([1]) == 0.0


def test_validate_group_and_heal_run() -> None:
    cands = [_candidate(i * 50, i + 1) for i in range(5)]
    run = validate_group(cands, strategy="test")
    assert run is not None
    assert run.monotone_fraction == 1.0
    assert len(run.candidates) == 5

    # Run with detour
    cands_with_detour = [
        _candidate(0, 1),
        _candidate(50, 999),  # detour spike
        _candidate(100, 2),
        _candidate(150, 3),
        _candidate(200, 4),
    ]
    rough_run = validate_group(cands_with_detour, min_monotone=0.5, strategy="rough")
    assert rough_run is not None
    healed, _inferred, _promoted = heal_run(rough_run)
    assert len(healed.candidates) == 4
    assert [c.value for c in healed.candidates] == [1, 2, 3, 4]


def test_unify_alternating_runs() -> None:
    # Odd pages
    run_odd = validate_group(
        [_candidate(0, 1), _candidate(100, 3), _candidate(200, 5)],
        strategy="odd",
        min_monotone=0.8,
    )
    # Even pages
    run_even = validate_group(
        [_candidate(50, 2), _candidate(150, 4), _candidate(250, 6)],
        strategy="even",
        min_monotone=0.8,
    )
    assert run_odd is not None
    assert run_even is not None

    unified = unify_alternating_runs([run_odd, run_even])
    assert len(unified) == 1
    assert [c.value for c in unified[0].candidates] == [1, 2, 3, 4, 5, 6]
