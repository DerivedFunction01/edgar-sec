"""Feeds CLI: parser shape and dispatch over the typed options model."""

from __future__ import annotations

from pathlib import Path

import edgar_sec.pipelines.feeds.cli as cli
from edgar_sec.pipelines.feeds.options import FeedsOptions


def test_backfill_dispatch_parses_the_month_range(tmp_path: Path, monkeypatch) -> None:
    captured: list[FeedsOptions] = []
    monkeypatch.setattr(
        cli, "cmd_backfill", lambda options: captured.append(options) or 0
    )
    rc = cli.main(
        [
            "backfill",
            "--start",
            "2026-07",
            "--end",
            "2026-09",
            "--artifacts",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert captured[0].start == (2026, 7)
    assert captured[0].end == (2026, 9)
    assert captured[0].artifacts_root == tmp_path.resolve()


def test_run_dispatch_defaults_to_all_four_feeds(monkeypatch) -> None:
    captured: list[FeedsOptions] = []
    monkeypatch.setattr(cli, "cmd_run", lambda options: captured.append(options) or 0)
    assert cli.main(["run"]) == 0
    assert captured[0].feeds == ("usgaap", "risk_return", "inline", "all")


def test_invalid_month_is_an_error_not_a_traceback() -> None:
    assert cli.main(["backfill", "--start", "2026-13", "--end", "2026-13"]) == 1


def test_status_dispatch(monkeypatch) -> None:
    captured: list[FeedsOptions] = []
    monkeypatch.setattr(
        cli, "cmd_status", lambda options: captured.append(options) or 0
    )
    assert cli.main(["status", "--branch", "main"]) == 0
    assert captured[0].branch == "main"
