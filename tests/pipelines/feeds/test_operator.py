"""Feeds operator: menu shape and session header over the same commands."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.pipelines.feeds.operator import (
    WizardState,
    build_operator_menu,
    render_session_header,
)


def test_menu_offers_run_backfill_and_status() -> None:
    labels = [action.label for action in build_operator_menu(WizardState())]
    assert "Run live feeds" in labels
    assert "Backfill monthly archives" in labels
    assert "Ledger status" in labels


def test_session_header_reports_absence_on_an_empty_root(tmp_path: Path) -> None:
    state = WizardState(artifacts_root=str(tmp_path))
    assert render_session_header(state) == "no ledger published"


def test_state_options_carry_the_session_root(tmp_path: Path) -> None:
    state = WizardState(artifacts_root=str(tmp_path))
    options = state.options()
    assert options.artifacts_root == tmp_path.resolve()
    assert options.feeds == ("usgaap", "risk_return", "inline", "all")
