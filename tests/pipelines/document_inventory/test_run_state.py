from __future__ import annotations

from edgar_sec.pipelines.document_inventory.paths import (
    PROJECTION_MANIFEST_FILE,
    InventoryPaths,
    inventory_run_paths,
)
from edgar_sec.pipelines.document_inventory.run_state import (
    discover_run_statuses,
    load_run_status,
)


def test_empty_run_discovery_has_no_filesystem_side_effects(tmp_path) -> None:
    assert discover_run_statuses(tmp_path) == ()
    assert not InventoryPaths(tmp_path).transient_root.exists()
    assert not InventoryPaths(tmp_path).snapshots_root.exists()


def test_malformed_run_is_reported_without_repair(tmp_path) -> None:
    paths = inventory_run_paths(tmp_path, "run-invalid")
    paths.run_root.mkdir(parents=True)
    manifest = paths.run_root / PROJECTION_MANIFEST_FILE
    manifest.write_text("not json", encoding="utf-8")
    original = manifest.read_bytes()

    status = load_run_status(tmp_path, paths.run_id)

    assert not status.valid
    assert status.state == "invalid"
    assert manifest.read_bytes() == original
    assert not InventoryPaths(tmp_path).snapshots_root.exists()


def test_discovery_reports_partial_run_and_skips_unrelated_directories(
    tmp_path,
) -> None:
    paths = inventory_run_paths(tmp_path, "run-partial")
    paths.run_root.mkdir(parents=True)
    (paths.run_root / PROJECTION_MANIFEST_FILE).write_text("{}", encoding="utf-8")
    (paths.run_root.parent / "unrelated").mkdir()

    statuses = discover_run_statuses(tmp_path)

    assert len(statuses) == 1
    assert statuses[0].run_id == paths.run_id
    assert not statuses[0].valid
