"""Facts publication: DAG snapshot with archive-SHA lineage, no-op republish."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.pipelines.metadata_sync.facts_publish import facts_tip, publish_facts
from edgar_sec.pipelines.metadata_sync.facts_store import ingest_facts_archive
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from tests.pipelines.metadata_sync.test_facts_store import _store_archive, _member


def test_publish_records_archive_lineage_and_republish_is_a_noop(
    tmp_path: Path,
) -> None:
    paths = resolve_metadata_paths(tmp_path)
    assert publish_facts(paths).published is False

    reference = _store_archive(
        tmp_path,
        {"CIK0000320193.json": _member("Apple", 300)},
        "only.zip",
    )
    ingest_facts_archive(paths, reference, workers=1)

    outcome = publish_facts(paths)
    assert outcome.published is True
    assert outcome.snapshot_id is not None
    assert outcome.snapshot_id.startswith("companyfacts-")
    assert outcome.tip_before is None
    assert facts_tip(paths) == outcome.snapshot_id

    catalog = DAGCatalog(paths.facts_snapshots_root, read_only=True)
    manifest = catalog.get_manifest(outcome.snapshot_id)
    assert manifest is not None
    assert manifest.metadata["archive_sha256"] == reference.sha256
    assert manifest.metadata["source_id"] == "companyfacts_bulk"
    assert set(manifest.relations) == {"company_facts", "fact_members", "fact_archives"}
    part = manifest.relations["company_facts"][0]
    assert part.row_count == 2

    again = publish_facts(paths)
    assert again.published is False
    assert again.snapshot_id is None
    assert again.tip_before == outcome.snapshot_id
