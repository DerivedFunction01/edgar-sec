"""Options and paths: the datasets layout resolves under one root."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.pipelines.datasets.options import datasets_options


def test_options_resolve_the_store_layout(tmp_path: Path) -> None:
    paths = datasets_options(artifacts_root=tmp_path).datasets_paths()
    assert paths.store_file == tmp_path / "datasets" / "datasets.duckdb"
    assert paths.bulk_archives_root == tmp_path / "bulk_archives"
    assert paths.snapshots_root == tmp_path / "datasets" / "snapshots"
