"""Tests for interactive distribution menu configuration and dashboard."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.infra.distribution.menu import (
    DistribMenuConfig,
    create_distrib_menu,
    render_distrib_dashboard,
)

from .test_cli import DummyAdapter


def test_distrib_menu_config_and_dashboard(tmp_path: Path) -> None:
    """Verifies menu configuration resolves paths and generates dashboard text."""
    adapter = DummyAdapter()
    config = DistribMenuConfig(
        adapter=adapter,
        plan_id_provider=lambda: "p1",
        distribution_root=tmp_path,
    )
    assert config.resolve_root() == tmp_path.resolve()

    dashboard = render_distrib_dashboard(config)
    assert "Worker Distribution Console" in dashboard
    assert "Active Plan: p1" in dashboard

    menu_actions = create_distrib_menu(config)
    assert len(menu_actions) == 5
