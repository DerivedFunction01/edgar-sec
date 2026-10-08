"""Tests for interactive distribution menu configuration and dashboard."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_distrib_menu_session_plans_root_auto_pick(tmp_path: Path) -> None:
    """Verifies single plan in plans_root is auto-picked by session."""
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
    session = DistribSession()
    assert session.get_or_prompt_plan(config) == "p100"
    assert session.plan_id == "p100"
