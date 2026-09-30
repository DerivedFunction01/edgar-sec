"""Unit tests for apps.viewer.loaders."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from edgar_sec.apps.viewer.loaders import (
    LOADERS,
    iter_documents,
    load_document_storage,
    load_filing_catalog,
    load_metadata,
    load_sqlite_databases,
    load_transient_runs,
    run_all,
)
from edgar_sec.pipelines.metadata_sync.paths import MetadataPaths
from tests.apps.viewer.conftest import (
    build_metadata_snapshot,
    build_transient_run,
)


def _kinds(items: list) -> set[str]:
    return {item.kind for item in items}


def test_loader_registry_covers_every_published_dataset() -> None:
    assert {loader.name for loader in LOADERS} == {
        "metadata",
        "filing_catalog",
        "document_storage",
        "sqlite",
        "transient",
    }


def test_a_multipart_metadata_snapshot_is_one_record_plus_its_cik_index(
    metadata_tree: Path,
) -> None:
    found = load_metadata(metadata_tree)
    assert _kinds(found) == {"metadata_snapshot", "metadata_cik_index"}
    payload = next(item for item in found if item.kind == "metadata_snapshot")
    assert len(payload.source_paths) == 2
    assert all(path.endswith(".parquet") for path in payload.source_paths)
    assert payload.revision


def test_metadata_snapshot_records_the_plan_as_run_id(metadata_tree: Path) -> None:
    payload = next(
        item
        for item in load_metadata(metadata_tree)
        if item.kind == "metadata_snapshot"
    )
    assert payload.run_id == "plan-meta"


def test_a_tampered_part_removes_the_snapshot_rather_than_lying(
    metadata_tree: Path,
) -> None:
    """A digest mismatch must not yield a browsable dataset with wrong contents."""
    paths = MetadataPaths(artifacts_root=metadata_tree)
    part = paths.snapshot_part("snap-meta", "part-00000.parquet")
    part.write_bytes(b"not the published bytes")

    found = load_metadata(metadata_tree)
    assert "metadata_snapshot" not in _kinds(found)
    # The CIK index has no dependency on the payload, so it survives.
    assert "metadata_cik_index" in _kinds(found)


def test_an_unpublished_metadata_run_is_invisible(metadata_tree: Path) -> None:
    """A snapshot directory without a manifest is not a snapshot."""
    (MetadataPaths(artifacts_root=metadata_tree).snapshots_root / "in-progress").mkdir()
    assert all(
        "in-progress" not in item.relative_path for item in load_metadata(metadata_tree)
    )


def test_a_missing_declared_part_removes_the_snapshot(metadata_tree: Path) -> None:
    paths = MetadataPaths(artifacts_root=metadata_tree)
    paths.snapshot_part("snap-meta", "part-00001.parquet").unlink()
    assert "metadata_snapshot" not in _kinds(load_metadata(metadata_tree))


def test_catalog_snapshot_yields_profiles_and_one_targets_record(
    catalog_tree: Path,
) -> None:
    found = load_filing_catalog(catalog_tree)
    assert _kinds(found) == {"catalog_profiles", "catalog_targets"}
    targets = next(item for item in found if item.kind == "catalog_targets")
    assert len(targets.source_paths) == 2


def test_document_snapshot_splits_index_from_payload(document_tree: Path) -> None:
    found = load_document_storage(document_tree)
    assert _kinds(found) == {"document_index", "document_payload"}
    assert all(item.run_id == "run-doc" for item in found)


def test_profiles_and_targets_share_one_revision(catalog_tree: Path) -> None:
    """Both tables of a catalog come from the same manifest, so same token."""
    found = load_filing_catalog(catalog_tree)
    assert len({item.revision for item in found}) == 1


def test_a_transient_run_becomes_one_union_record(transient_tree: Path) -> None:
    found = load_transient_runs(transient_tree)
    assert len(found) == 1
    union = found[0]
    assert union.kind == "metadata_run_union"
    assert union.run_id == "run-1"
    assert len(union.source_paths) == 3


def test_a_single_chunk_is_listed_as_itself_not_a_union(
    artifacts_root: Path,
) -> None:
    build_transient_run(artifacts_root, chunk_count=1)
    found = load_transient_runs(artifacts_root)
    assert [item.kind for item in found] == ["metadata_chunk"]


def test_union_revision_changes_when_a_chunk_arrives(transient_tree: Path) -> None:
    before = load_transient_runs(transient_tree)[0].revision
    build_transient_run(transient_tree, chunk_count=4)
    after = load_transient_runs(transient_tree)[0].revision
    assert before != after


def test_sqlite_database_is_exposed_one_record_per_table(sqlite_tree: Path) -> None:
    found = load_sqlite_databases(sqlite_tree)
    assert [item.table for item in found] == ["payloads"]
    assert found[0].format == "sqlite"


def test_run_all_combines_every_loader_without_duplicates(
    full_tree: Callable[[Path], Path], artifacts_root: Path
) -> None:
    full_tree(artifacts_root)
    found = run_all(artifacts_root)
    assert len({item.id for item in found}) == len(found)
    assert len(found) >= 7


def test_run_all_survives_an_unreadable_manifest(artifacts_root: Path) -> None:
    """One damaged snapshot must not hide the healthy ones."""
    build_metadata_snapshot(artifacts_root)
    broken = MetadataPaths(artifacts_root=artifacts_root).snapshot_dir("broken")
    broken.mkdir(parents=True)
    (broken / "metadata.manifest.json").write_text("{not json", encoding="utf-8")
    found = run_all(artifacts_root)
    assert any(item.kind == "metadata_snapshot" for item in found)


def test_documents_list_manifests_separately_from_datasets(
    metadata_tree: Path,
) -> None:
    documents = iter_documents(metadata_tree)
    assert [item.format for item in documents] == ["json"]
    assert all(
        item.relative_path.endswith("metadata.manifest.json") for item in documents
    )


def test_an_empty_root_yields_nothing(artifacts_root: Path) -> None:
    assert run_all(artifacts_root) == []
    assert iter_documents(artifacts_root) == []
