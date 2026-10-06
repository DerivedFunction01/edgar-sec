"""Inventory run/chunk/attempt path contracts for S4.

Validated IDs never escape the run tree; published snapshot paths stay separate
from transient run state.
"""

from pathlib import Path

import pytest

from edgar_sec.pipelines.document_inventory.paths import (
    CHUNKS_DIR,
    DATASET,
    OUTCOMES_FILE,
    PUBLICATION_DIR,
    RUN_MANIFEST_FILE,
    SNAPSHOTS_DIR,
    inventory_run_paths,
)


def test_run_root_lies_under_transient_dataset(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    assert paths.run_root == tmp_path / "transient" / DATASET / "run-1"


def test_snapshots_root_stays_out_of_transient(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    assert paths.snapshots_root == tmp_path / DATASET / SNAPSHOTS_DIR
    assert "transient" not in paths.snapshots_root.parts
    assert paths.run_root != paths.snapshots_root


def test_run_manifest_lock_and_publication_paths(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    assert paths.run_manifest_path() == paths.run_root / RUN_MANIFEST_FILE
    assert paths.lock_path() == paths.run_root / "run.lock"
    assert paths.publication_dir() == paths.run_root / PUBLICATION_DIR


def test_chunk_and_attempt_layout_matches_plan(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    chunk = paths.chunk_dir("chunk-000000-abcd1234")
    assert chunk == paths.run_root / CHUNKS_DIR / "chunk-000000-abcd1234"
    assert paths.chunk_pointer_path("chunk-000000-abcd1234") == chunk / "current.json"
    attempt = paths.attempt_dir("chunk-000000-abcd1234", "cafebabe")
    assert attempt.name == "attempt-cafebabe"
    assert attempt.parent == chunk
    assert paths.attempt_outcomes_path("chunk-000000-abcd1234", "cafebabe") == (
        attempt / OUTCOMES_FILE
    )
    assert paths.attempt_entries_path("chunk-000000-abcd1234", "cafebabe").name == (
        "entries.parquet"
    )
    assert paths.attempt_manifest_path("chunk-000000-abcd1234", "cafebabe").name == (
        "manifest.json"
    )


@pytest.mark.parametrize(
    "bad_id",
    ["", ".", "..", "../etc", "a/b", "a\\b", "a b", "a\nb", "a\x00b"],
)
def test_unsafe_ids_are_refused(tmp_path: Path, bad_id: str) -> None:
    with pytest.raises(ValueError):
        inventory_run_paths(tmp_path, bad_id)


@pytest.mark.parametrize("bad_id", ["..", "a/b", ""])
def test_chunk_and_attempt_ids_are_validated(tmp_path: Path, bad_id: str) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    with pytest.raises(ValueError):
        paths.chunk_dir(bad_id)
    with pytest.raises(ValueError):
        paths.attempt_dir("chunk-000000-abcd1234", bad_id)


def test_paths_create_nothing_on_disk(tmp_path: Path) -> None:
    inventory_run_paths(tmp_path, "run-1")
    assert list(tmp_path.iterdir()) == []
