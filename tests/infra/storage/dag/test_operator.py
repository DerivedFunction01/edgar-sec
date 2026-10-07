"""Tests for standalone interactive DAG operator entrypoint."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.infra.storage.dag.operator import (
    discover_snapshot_repositories,
    main,
)


def test_discover_snapshot_repositories_finds_local(
    tmp_path: Path, monkeypatch
) -> None:
    cwd = tmp_path / "repo"
    cwd.mkdir()
    snaps = cwd / "snapshots"
    (snaps / "current").mkdir(parents=True)
    monkeypatch.chdir(cwd)
    repos = discover_snapshot_repositories()
    assert any(p == snaps for _, p in repos)


def test_main_dispatches_when_no_repos(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "edgar_sec.infra.storage.dag.operator.run_dag_menu", lambda _cfg, _argv: 42
    )
    assert main([]) == 42
