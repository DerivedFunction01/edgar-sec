"""Tests for interactive distribution menu work selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.infra.distribution.menu import (
    DistribMenuConfig,
    DistribSession,
    create_distrib_menu,
    render_distrib_dashboard,
)
from edgar_sec.infra.distribution.protocol import DistributionWork

from .test_cli import DummyAdapter


def test_distrib_menu_config_and_dashboard(tmp_path: Path) -> None:
    adapter = DummyAdapter()
    config = DistribMenuConfig(
        adapter=adapter,
        work_id="work-1",
        distribution_root=tmp_path,
    )
    assert config.resolve_root() == tmp_path.resolve()

    dashboard = render_distrib_dashboard(config)
    assert "Worker Distribution Console" in dashboard
    assert "Active Work: Mock work [work-1]" in dashboard

    menu_actions = create_distrib_menu(config)
    assert len(menu_actions) == 6


def test_distrib_session_selects_adapter_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = DummyAdapter()
    config = DistribMenuConfig(adapter=adapter, distribution_root=tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: "")
    session = DistribSession()
    assert session.get_or_prompt_work(config) == "work-1"
    assert session.work_id == "work-1"


def test_distrib_menu_switch_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar_sec.infra.distribution.menu import _action_switch_work

    class TwoWorkAdapter(DummyAdapter):
        def list_work_items(self, artifacts_root: Path | None = None):
            return (
                DistributionWork("work-1", "First", self.work_digest, 4),
                DistributionWork("work-2", "Second", "other-digest", 2),
            )

    adapter = TwoWorkAdapter()
    config = DistribMenuConfig(adapter=adapter, distribution_root=tmp_path)
    actions = create_distrib_menu(config)
    assert len(actions) == 6
    assert any("switch active work" in action.label.lower() for action in actions)

    session = DistribSession("work-1")
    monkeypatch.setattr("builtins.input", lambda _: "2")
    _action_switch_work(config, session)
    assert session.work_id == "work-2"
