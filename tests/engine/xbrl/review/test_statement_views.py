"""Statement-view driver scoring: totals, blocked pins, load failures."""

from __future__ import annotations

from typing import Any

from edgar_sec.engine.xbrl.review.statement_views import (
    BlockedCell,
    StatementViewExpectations,
    score_statement_views,
    summarize_driver_report,
)


def _report() -> dict[str, Any]:
    """A two-filing driver report with one blocked cell."""
    return {
        "filings": {
            "a_10k": {
                "classification": {
                    "financials.revenue": {
                        "classification": "served-faithful",
                        "mechanism": None,
                    },
                    "financials.capex": {
                        "classification": "blocked",
                        "mechanism": "served value not in filed facts",
                    },
                }
            },
            "b_10q": {
                "classification": {
                    "financials.revenue": {
                        "classification": "served-honest",
                        "mechanism": None,
                    }
                }
            },
        }
    }


def _expectations(**overrides: Any) -> StatementViewExpectations:
    """Expectations matching _report, with per-test overrides."""
    base: dict[str, Any] = {
        "cells": 3,
        "faithful": 1,
        "honest": 1,
        "blocked": 1,
        "blocked_cells": (
            BlockedCell(
                folder="a_10k",
                cell="financials.capex",
                mechanism="served value not in filed facts",
                disposition="recorded carry",
            ),
        ),
    }
    base.update(overrides)
    return StatementViewExpectations(**base)


def test_summarize_counts_and_blocked() -> None:
    """Summary counts every cell and lists blocked cells with mechanisms."""
    summary = summarize_driver_report(_report())
    assert summary["cells"] == 3
    assert summary["faithful"] == 1
    assert summary["honest"] == 1
    assert summary["blocked"] == 1
    assert summary["blocked_cells"] == [
        {
            "folder": "a_10k",
            "cell": "financials.capex",
            "mechanism": "served value not in filed facts",
        }
    ]
    assert summary["load_errors"] == []


def test_score_passes_on_exact_match() -> None:
    """A report matching the pins scores clean."""
    assert score_statement_views(_report(), _expectations()).passed


def test_score_fails_on_total_movement() -> None:
    """A moved total fails with the field named."""
    score = score_statement_views(_report(), _expectations(faithful=2))
    assert not score.passed
    assert any("faithful" in failure for failure in score.failures)


def test_score_fails_on_unpinned_and_absent_blocked() -> None:
    """Blocked cells must match the pinned set in both directions."""
    score = score_statement_views(_report(), _expectations(blocked_cells=()))
    assert not score.passed
    assert any("not pinned" in failure for failure in score.failures)
    moved = _report()
    moved["filings"]["a_10k"]["classification"]["financials.capex"] = {
        "classification": "served-faithful",
        "mechanism": None,
    }
    score = score_statement_views(
        moved, _expectations(cells=3, faithful=2, honest=1, blocked=0)
    )
    assert not score.passed
    assert any("pinned but absent" in failure for failure in score.failures)


def test_score_fails_on_load_error() -> None:
    """A filing that failed to load fails the gate by name."""
    report = _report()
    report["filings"]["c_10k"] = {"load_error": "ValueError: boom"}
    score = score_statement_views(report, _expectations())
    assert not score.passed
    assert any("c_10k" in failure for failure in score.failures)
