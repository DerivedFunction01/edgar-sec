"""Tests for paginated interactive DAG menu and dashboard."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from edgar_sec.infra.storage.dag.menu import (
    DAGMenuConfig,
    PickItem,
    create_dag_menu,
    prompt_paginated_choice,
    render_dag_dashboard,
)


def test_prompt_paginated_choice_selects_item(monkeypatch) -> None:
    items = [
        PickItem(key="b1", label="Branch One", value="b1"),
        PickItem(key="b2", label="Branch Two", value="b2"),
    ]
    monkeypatch.setattr(
        "edgar_sec.infra.storage.dag.menu.prompt_text", lambda *_args: "1"
    )
    chosen = prompt_paginated_choice(items, page_size=10)
    assert chosen is not None
    assert chosen.key == "b1"


def test_prompt_paginated_choice_filters_and_quits(monkeypatch) -> None:
    items = [
        PickItem(key="main", label="main branch", value="main"),
        PickItem(key="feature", label="feature branch", value="feature"),
    ]
    prompts = iter(["feat", "1"])
    monkeypatch.setattr(
        "edgar_sec.infra.storage.dag.menu.prompt_text", lambda *_args: next(prompts)
    )
    chosen = prompt_paginated_choice(items, page_size=10)
    assert chosen is not None
    assert chosen.key == "feature"


def test_render_dag_dashboard_runs(tmp_path: Path) -> None:
    config = DAGMenuConfig(snapshots_root=tmp_path, title="Test Console")
    out = render_dag_dashboard(config)
    assert "Test Console" in out
    assert "HEAD: No active pointer" in out


def test_create_dag_menu_includes_publish_action(tmp_path: Path) -> None:
    mock_pub = MagicMock()
    config = DAGMenuConfig(
        snapshots_root=tmp_path,
        publish_action=mock_pub,
        publish_label="Custom Publish",
    )
    menu = create_dag_menu(config)
    labels = [action.label for action in menu]
    assert "Custom Publish" in labels
    assert any("swimlane" in label.lower() for label in labels)
    assert any("doctor" in label.lower() for label in labels)


def test_create_dag_menu_omits_publish_when_none(tmp_path: Path) -> None:
    config = DAGMenuConfig(snapshots_root=tmp_path, publish_action=None)
    menu = create_dag_menu(config)
    labels = [action.label for action in menu]
    assert not any("Custom Publish" in label for label in labels)
