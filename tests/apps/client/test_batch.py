"""Batch streaming contract: bounded lifetimes, per-filing failures."""

from __future__ import annotations

import os
import time

from edgar_sec.apps.client.batch import FilingOutcome, stream_filing_outcomes


def _length_or_raise(unit: str) -> int:
    """The unit's length, except one unit that always fails."""
    if unit == "bad":
        raise ValueError("boom")
    return len(unit)


def _length_or_crash(unit: str) -> int:
    """The unit's length, except one unit that kills its worker process."""
    if unit == "crash":
        os._exit(42)
    time.sleep(0.3)
    return len(unit)


def test_sequential_outcomes_carry_values_and_named_errors() -> None:
    """Sequential outcomes arrive in order; a failure is named, not raised."""
    outcomes = list(
        stream_filing_outcomes(["aa", "bad", "cccc"], _length_or_raise, workers=1)
    )
    assert [outcome.unit for outcome in outcomes] == ["aa", "bad", "cccc"]
    assert [outcome.value for outcome in outcomes] == [2, None, 4]
    assert outcomes[1].error == "ValueError: boom"
    assert [outcome.ok for outcome in outcomes] == [True, False, True]


def test_pool_outcomes_equal_sequential_outcomes() -> None:
    """The pool changes lifetimes only: per-unit results are unchanged."""
    units = ["aa", "bad", "cccc", "d", "ee", "fff", "gg", "hhhhh"]

    def by_unit(outcomes: list[FilingOutcome[str, int]]) -> dict[str, tuple]:
        return {o.unit: (o.value, o.error) for o in outcomes}

    sequential = by_unit(
        list(stream_filing_outcomes(units, _length_or_raise, workers=1))
    )
    pooled = by_unit(list(stream_filing_outcomes(units, _length_or_raise, workers=2)))
    assert pooled == sequential


def test_worker_crash_fails_its_window_not_the_run() -> None:
    """A worker's death errors its in-flight filings; the run completes."""
    units = ["crash"] + [f"u{i}" for i in range(7)]
    outcomes = {
        o.unit: o for o in stream_filing_outcomes(units, _length_or_crash, workers=2)
    }
    assert set(outcomes) == set(units)
    assert outcomes["crash"].error is not None
    assert outcomes["crash"].error.startswith("BrokenProcessPool")
    assert all(outcomes[f"u{i}"].ok for i in range(4, 7))
