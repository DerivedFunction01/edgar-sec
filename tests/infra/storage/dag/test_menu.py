"""Tests for paginated interactive DAG menu and dashboard."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

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


def test_collect_dag_targets_empty(tmp_path: Path) -> None:
    from edgar_sec.infra.storage.dag.menu import collect_dag_targets

    assert collect_dag_targets(tmp_path) == []


def test_collect_and_prompt_dag_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar_sec.infra.storage.dag.catalog import DAGCatalog
    from edgar_sec.infra.storage.dag.menu import collect_dag_targets, prompt_dag_target

    catalog = DAGCatalog(tmp_path)
    catalog.write_pointer("current", "snap-1")
    catalog.write_pointer("develop", "snap-2")
    catalog.create_tag("v1.0", "snap-1")

    items = collect_dag_targets(tmp_path)
    assert len(items) == 3
    assert items[0].key == "current"
    assert items[0].value == "snap-1"

    monkeypatch.setattr("builtins.input", lambda _: "")
    chosen = prompt_dag_target(tmp_path)
    assert chosen == "snap-1"


def test_action_branch_list_and_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest
    from edgar_sec.infra.storage.dag.catalog import DAGCatalog
    from edgar_sec.infra.storage.dag.menu import _action_branch

    catalog = DAGCatalog(tmp_path)
    manifest = DAGNodeManifest(
        snapshot_id="snap-1",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="snap-1",
        logical_fingerprint="fp-1",
        lineage_depth=0,
        created_at="2024-01-01T00:00:00Z",
        relations={},
    )
    catalog.publish_node(manifest, branch_name="current")

    inputs = iter(["2", "feature-x", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    config = DAGMenuConfig(snapshots_root=tmp_path)
    _action_branch(config)

    branches = catalog.list_branches()
    assert "feature-x" in branches


def test_action_tag_create(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest
    from edgar_sec.infra.storage.dag.catalog import DAGCatalog
    from edgar_sec.infra.storage.dag.menu import _action_tag

    catalog = DAGCatalog(tmp_path)
    manifest = DAGNodeManifest(
        snapshot_id="snap-1",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="snap-1",
        logical_fingerprint="fp-1",
        lineage_depth=0,
        created_at="2024-01-01T00:00:00Z",
        relations={},
    )
    catalog.publish_node(manifest, branch_name="current")

    inputs = iter(["2", "v2.0", "", "test release"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    config = DAGMenuConfig(snapshots_root=tmp_path)
    _action_tag(config)

    tags = catalog.list_tags()
    assert any(t["name"] == "v2.0" for t in tags)
