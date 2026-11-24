"""Snapshot installation: parent-input staging, tree sync, pointer reads."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from edgar_sec.foundation.runtime.paths import part_file_name
from edgar_sec.infra.storage.atomic import _fsync_dir
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.snapshot.merge_relations import (
    _parent_relation_files,
)
from edgar_sec.pipelines.document_inventory.snapshot.validation import (
    validate_snapshot,
)


def _read_pointer(paths: InventoryPaths) -> str | None:
    catalog = DAGCatalog(paths.snapshots_root)
    if catalog.catalog_file.is_file():
        ptr = catalog.read_pointer()
        if ptr:
            return str(ptr["snapshot_id"])
    return None


def _make_parent_input_dirs(
    stage_parent: Path,
    inventory_paths: InventoryPaths,
    parent_snapshot_id: str | None,
) -> tuple[Path | None, Path | None]:
    if parent_snapshot_id is None:
        return None, None
    roots = []
    for relation in ("accessions", "accession_sources"):
        root = stage_parent / "parent-input" / relation
        root.mkdir(parents=True)
        files = _parent_relation_files(inventory_paths, parent_snapshot_id, relation)
        for index, source in enumerate(files):
            os.symlink(source, root / part_file_name(index))
        roots.append(root if any(root.iterdir()) else None)
    return roots[0], roots[1]


def _sync_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        _fsync_dir(str(directory))
    _fsync_dir(str(root))


def _install_snapshot(
    paths: InventoryPaths, snapshot_id: str, staged_root: Path, profile
) -> Path:
    destination = paths.snapshot_root(snapshot_id)
    if destination.exists():
        validate_snapshot(paths, snapshot_id, profile=profile)
        return destination
    installation = paths.snapshots_root / f".install-{snapshot_id}-{uuid.uuid4().hex}"
    try:
        shutil.copytree(staged_root, installation)
        _sync_tree(installation)
        os.replace(installation, destination)
        _fsync_dir(str(paths.snapshots_root))
    finally:
        if installation.exists():
            shutil.rmtree(installation)
    return destination
