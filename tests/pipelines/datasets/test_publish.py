"""Publish: the index snapshot lands in the DAG and a re-publish is a no-op."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.pipelines.datasets.ingest import import_local_archive
from edgar_sec.pipelines.datasets.paths import resolve_datasets_paths
from edgar_sec.pipelines.datasets.publish import publish_index, store_tip
from edgar_sec.pipelines.datasets.specs import spec_for
from tests.support import fixture_path


def test_publish_index_and_noop_republish(tmp_path: Path) -> None:
    paths = resolve_datasets_paths(tmp_path)
    assert store_tip(paths) is None
    import_local_archive(
        paths,
        spec_for("mfrr"),
        "2010q4",
        fixture_path("datasets/mfrr_2010q4_specimen.zip"),
        source_url="https://www.sec.gov/example.zip",
        loaded_at="2026-11-08T00:00:00+00:00",
    )
    first = publish_index(paths)
    assert first.published
    assert first.snapshot_id is not None
    assert store_tip(paths) == first.snapshot_id
    snapshot_dir = paths.snapshot_dir(first.snapshot_id)
    assert (snapshot_dir / "dataset_vintages.parquet").is_file()
    second = publish_index(paths)
    assert not second.published
    assert store_tip(paths) == first.snapshot_id
