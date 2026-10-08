"""Tests for interactive distribution menu configuration and dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.infra.distribution.menu import (
    DistribMenuConfig,
    DistribSession,
    create_distrib_menu,
    render_distrib_dashboard,
)

from .test_cli import DummyAdapter


def test_distrib_menu_config_and_dashboard(tmp_path: Path) -> None:
    """Verifies menu configuration resolves paths and generates dashboard text."""
    adapter = DummyAdapter()
    config = DistribMenuConfig(
        adapter=adapter,
        plan_id="p1",
        distribution_root=tmp_path,
    )
    assert config.resolve_root() == tmp_path.resolve()

    dashboard = render_distrib_dashboard(config)
    assert "Worker Distribution Console" in dashboard
    assert "Active Plan: p1" in dashboard

    menu_actions = create_distrib_menu(config)
    assert len(menu_actions) == 5


def test_distrib_menu_session_plans_root_auto_pick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies single plan in plans_root is default-picked with enter."""
    adapter = DummyAdapter()
    plans_dir = tmp_path / "plans"
    plan_subdir = plans_dir / "p100"
    plan_subdir.mkdir(parents=True)
    (plan_subdir / "plan.json").write_text(
        json.dumps({"plan_id": "p100"}), encoding="utf-8"
    )

    config = DistribMenuConfig(
        adapter=adapter,
        plans_root=plans_dir,
        distribution_root=tmp_path,
    )
    monkeypatch.setattr("builtins.input", lambda _: "")
    session = DistribSession()
    assert session.get_or_prompt_plan(config) == "p100"
    assert session.plan_id == "p100"


def test_distrib_menu_switch_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar_sec.infra.distribution.menu import _action_switch_plan

    adapter = DummyAdapter()
    plans_dir = tmp_path / "plans"
    for pid in ("plan-1", "plan-2"):
        pdir = plans_dir / pid
        pdir.mkdir(parents=True)
        (pdir / "plan.json").write_text(json.dumps({"plan_id": pid}), encoding="utf-8")

    config = DistribMenuConfig(
        adapter=adapter,
        plans_root=plans_dir,
        distribution_root=tmp_path,
    )
    menu_actions = create_distrib_menu(config)
    assert len(menu_actions) == 6
    assert any("switch active plan" in a.label.lower() for a in menu_actions)

    session = DistribSession("plan-1")
    monkeypatch.setattr("builtins.input", lambda _: "1")
    _action_switch_plan(config, session)
    assert session.plan_id == "plan-2"
