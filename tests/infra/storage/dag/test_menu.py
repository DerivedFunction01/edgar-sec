"""Tests for paginated interactive DAG menu and dashboard."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from edgar_sec.infra.storage.dag.menu import (
    DAGMenuConfig,
    create_dag_menu,
    render_dag_dashboard,
)


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


def test_create_dag_menu_keys_are_contiguous_when_publish_is_none(
    tmp_path: Path,
) -> None:
    config = DAGMenuConfig(snapshots_root=tmp_path, publish_action=None)
    menu = create_dag_menu(config)
    assert [action.key for action in menu] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
    ]


def test_create_dag_menu_keys_are_contiguous_when_publish_is_present(
    tmp_path: Path,
) -> None:
    config = DAGMenuConfig(
        snapshots_root=tmp_path,
        publish_action=MagicMock(),
        publish_label="Custom Publish",
    )
    menu = create_dag_menu(config)
    assert [action.key for action in menu] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
    ]
