"""Catalog materialization: guards, source resolution, and the published layout."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.filing_catalog.schemas import (
    PROFILE_SCHEMA,
    TARGET_COLUMNS,
    TARGET_SCHEMA,
)
from edgar_sec.domain.submissions.schemas import (
    SCHEMA_VERSION as SOURCE_SCHEMA_VERSION,
)
from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.pipelines.filing_catalog.catalog_job import (
    CatalogError,
    materialize,
    resolve_source,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    resolve_filing_catalog_paths,
)
from tests.support import catalog_fixture_path

_BOOL_COLUMNS = {"is_xbrl", "is_inline_xbrl", "is_xbrl_numeric"}


def _expected_targets() -> list[dict[str, str]]:
    with catalog_fixture_path("expected_filing_targets.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        return list(csv.DictReader(handle))


def _coerce(column: str, raw: Any) -> Any:
    if column in _BOOL_COLUMNS:
        return raw in (True, "True")
    if column == "reported_size":
        return int(raw)
    return raw


# --- the three important guards ----------------------------------------


def test_guard_rejects_a_transient_chunk_path(tmp_path: Path) -> None:
    chunk = tmp_path / "chunks" / "chunk_0001.parquet"
    chunk.parent.mkdir(parents=True)
    chunk.write_bytes(b"not really parquet")
    with pytest.raises(CatalogError, match="finalized artifact"):
        materialize(chunk, tmp_path / "out")


@pytest.mark.parametrize("part", ["checkpoints", "workers"])
def test_guard_rejects_every_transient_component(tmp_path: Path, part: str) -> None:
    chunk = tmp_path / "transient" / part / "unit-1.parquet"
    chunk.parent.mkdir(parents=True)
    chunk.write_bytes(b"not really parquet")
    with pytest.raises(CatalogError, match="finalized artifact"):
        materialize(chunk, tmp_path / "out")


def test_guard_rejects_source_schema_drift(tmp_path: Path, sample_source: Path) -> None:
    table = pq.read_table(sample_source)
    drifted = table.drop_columns(["listings"])
    drifted_path = tmp_path / "drifted.parquet"
    pq.write_table(drifted, drifted_path)
    with pytest.raises(CatalogError, match="do not match submission_metadata"):
        materialize(drifted_path, tmp_path / "out")


def test_guard_accepts_the_unmodified_source(
    tmp_path: Path, sample_source: Path
) -> None:
    manifest = materialize(sample_source, tmp_path / "out")
    assert manifest["profile_row_count"] > 0


def test_guard_refuses_to_overwrite_a_published_snapshot(
    tmp_path: Path, sample_source: Path
) -> None:
    from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths

    artifacts_root = tmp_path / "art"
    first = materialize(sample_source, artifacts_root)
    with pytest.raises(CatalogError, match="immutable catalog snapshot"):
        materialize(sample_source, artifacts_root)
    snapshot = resolve_filing_catalog_paths(artifacts_root).snapshot_dir(
        str(first["catalog_id"])
    )
    assert (snapshot / "company_profiles.parquet").is_file()


# --- explicit source manifests ---------------------------------------------


def _phase1_manifest(sample_source: Path, root: Path) -> Path:
    """Write the manifest published beside a snapshot payload."""
    from edgar_sec.foundation.hashing import file_sha256

    payload = root / "snapshots" / "snap-1"
    payload.mkdir(parents=True)
    target = payload / "metadata.parquet"
    target.write_bytes(sample_source.read_bytes())

    manifest = payload / "metadata.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "snapshot_id": "snap-1",
                "parts": [
                    {
                        "path": str(target),
                        "sha256": file_sha256(target),
                        "row_count": pq.read_table(target).num_rows,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_source_manifest_resolves_the_parquet_payload(
    tmp_path: Path, sample_source: Path
) -> None:
    """A manifest is metadata; the Parquet it names is the data."""
    manifest = _phase1_manifest(sample_source, tmp_path / "art")

    dataset = resolve_source(None, manifest)

    assert dataset.part_count == 1
    source = dataset.first
    assert source.suffix == ".parquet", "the JSON manifest was returned as the source"
    assert dataset.handoff is not None and dataset.handoff["snapshot_id"] == "snap-1"
    assert pq.read_schema(source).names == SUBMISSION_METADATA_SCHEMA.names


def _multipart_manifest(sample_source: Path, root: Path, parts: int = 2) -> Path:
    """A row-count split would let the re-fetched registrant straddle two parts."""
    from edgar_sec.foundation.hashing import file_sha256

    payload = root / "snapshots" / "snap-multi"
    parts_dir = payload / "parts"
    parts_dir.mkdir(parents=True)
    table = pq.read_table(sample_source)

    # Keep every row of a CIK together, then distribute whole CIK groups evenly.
    groups: dict[str, list[int]] = {}
    for offset, cik in enumerate(table.column("cik").to_pylist()):
        groups.setdefault(str(cik), []).append(offset)
    ordered = [sorted(groups[cik]) for cik in sorted(groups)]
    per_part = max(1, -(-len(ordered) // parts))

    entries = []
    index = 0
    for start in range(0, len(ordered), per_part):
        offsets = [
            offset for group in ordered[start : start + per_part] for offset in group
        ]
        chunk = table.take(pa.array(offsets, type=pa.int64()))
        path = parts_dir / f"part-{index:05d}.parquet"
        pq.write_table(chunk, path)
        entries.append(
            {
                "path": f"parts/{path.name}",
                "part_index": index,
                "source": f"chunk:{index}",
                "row_count": chunk.num_rows,
                "byte_count": path.stat().st_size,
                "sha256": file_sha256(path),
                "schema_version": SOURCE_SCHEMA_VERSION,
            }
        )
        index += 1

    manifest = payload / "metadata.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": "2.0.0",
                "snapshot_id": "snap-multi",
                "output_path": "",
                "artifact_sha256": "",
                "row_count": table.num_rows,
                "part_count": index,
                "parts": entries,
                "schema_version": SOURCE_SCHEMA_VERSION,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_a_multipart_source_materializes_the_same_catalog(
    tmp_path: Path, sample_source: Path
) -> None:
    """Several parts and one file are the same dataset, so the catalog must match."""
    single_part = _phase1_manifest(sample_source, tmp_path / "single-art")
    multipart = _multipart_manifest(sample_source, tmp_path / "multi-art")

    from_single = materialize(
        None, tmp_path / "out-single", source_manifest=single_part
    )
    from_parts = materialize(None, tmp_path / "out-multi", source_manifest=multipart)

    assert from_parts["source_part_count"] > 1
    assert from_single["profile_row_count"] == from_parts["profile_row_count"]
    assert from_single["target_row_count"] == from_parts["target_row_count"]
    assert from_single["form_counts"] == from_parts["form_counts"]

    single_profiles = pq.read_table(
        resolve_filing_catalog_paths(tmp_path / "out-single").snapshot_profiles_file(
            "snap-1"
        )
    )
    multi_profiles = pq.read_table(
        resolve_filing_catalog_paths(tmp_path / "out-multi").snapshot_profiles_file(
            "snap-multi"
        )
    )
    assert single_profiles.equals(multi_profiles)


def test_a_multipart_source_with_a_tampered_part_is_refused(
    tmp_path: Path, sample_source: Path
) -> None:
    manifest = _multipart_manifest(sample_source, tmp_path / "art")
    victim = next((manifest.parent / "parts").glob("part-0000*.parquet"))
    victim.write_bytes(b"truncated")

    with pytest.raises(CatalogError, match="digest mismatch"):
        resolve_source(None, manifest)


def test_a_part_with_a_foreign_schema_is_refused(
    tmp_path: Path, sample_source: Path
) -> None:
    """A part without the source schema fails before any query."""
    from edgar_sec.infra.storage.parquet import write_parquet_table

    manifest = _multipart_manifest(sample_source, tmp_path / "art")
    victim = next((manifest.parent / "parts").glob("part-0000*.parquet"))
    write_parquet_table(pa.table({"cik": ["0000000001"]}), victim)

    with pytest.raises(CatalogError, match="digest mismatch"):
        resolve_source(None, manifest)

    # Re-point the manifest at the tampered part, and the schema guard catches it.
    document = json.loads(manifest.read_text(encoding="utf-8"))
    name = victim.name
    for part in document["parts"]:
        if part["path"].endswith(name):
            part["sha256"] = file_sha256(victim)
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(CatalogError, match="columns do not match"):
        materialize(None, tmp_path / "out", source_manifest=manifest)


def test_materialize_accepts_an_explicit_manifest(
    tmp_path: Path, sample_source: Path
) -> None:
    manifest = _phase1_manifest(sample_source, tmp_path / "art")
    result = materialize(None, tmp_path / "out", source_manifest=manifest)
    assert result["profile_row_count"] > 0


def test_source_manifest_rejects_a_tampered_payload(
    tmp_path: Path, sample_source: Path
) -> None:
    manifest = _phase1_manifest(sample_source, tmp_path / "art")
    payload = Path(json.loads(manifest.read_text(encoding="utf-8"))["parts"][0]["path"])
    table = pq.read_table(payload).drop_columns(["listings"])
    pq.write_table(table, payload)

    with pytest.raises(CatalogError, match="digest mismatch"):
        resolve_source(None, manifest)


def test_source_manifest_without_a_digest_is_refused(
    tmp_path: Path, sample_source: Path
) -> None:
    manifest = _phase1_manifest(sample_source, tmp_path / "art")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["parts"][0].pop("sha256")
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(CatalogError, match="has no digest"):
        resolve_source(None, manifest)


def test_source_manifest_without_an_output_path_is_refused(
    tmp_path: Path, sample_source: Path
) -> None:
    manifest = _phase1_manifest(sample_source, tmp_path / "art")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document.pop("parts")
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(CatalogError, match="names no payload"):
        resolve_source(None, manifest)


def test_missing_source_manifest_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="manifest does not exist"):
        resolve_source(None, tmp_path / "absent.manifest.json")


def test_explicit_output_root_never_advances_a_pointer(
    tmp_path: Path, sample_source: Path, catalog_paths: Any
) -> None:
    materialize(sample_source, tmp_path / "out")
    assert not catalog_paths.current_pointer.exists()


# --- source resolution ----------------------------------------------------


def test_resolve_source_rejects_a_missing_artifact(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="does not exist"):
        resolve_source(tmp_path / "nope.parquet")


def test_resolve_source_without_arguments_reports_no_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    with pytest.raises(CatalogError, match="no Phase 1 snapshot"):
        resolve_source(None)


# --- published artifacts --------------------------------------------------


# Names as literals: a rename must fail here, not be absorbed by a shared constant.
def test_snapshot_layout_matches_the_documented_contract(
    catalog_snapshot: tuple[dict[str, Any], Path],
) -> None:
    _, snapshot_dir = catalog_snapshot
    assert (snapshot_dir / "company_profiles.parquet").is_file()
    assert (snapshot_dir / "filing_targets" / "part-00000.parquet").is_file()
    assert (snapshot_dir / "snapshot.manifest.json").is_file()


def test_one_target_shard_is_written_per_source_part(
    tmp_path: Path, sample_source: Path
) -> None:
    """Sharding bounds memory: one source part is unnested per query."""
    manifest_path = _multipart_manifest(sample_source, tmp_path / "art", parts=3)
    manifest = materialize(None, tmp_path / "out", source_manifest=manifest_path)

    assert manifest["source_part_count"] == 3
    assert manifest["target_part_count"] == 3
    assert [part["path"] for part in manifest["parts"]] == [
        "filing_targets/part-00000.parquet",
        "filing_targets/part-00001.parquet",
        "filing_targets/part-00002.parquet",
    ]
    assert all(part["source_part"] for part in manifest["parts"])
    assert manifest["target_row_count"] == sum(
        part["row_count"] for part in manifest["parts"]
    )


def test_form_counts_sum_across_shards(tmp_path: Path, sample_source: Path) -> None:
    """Per-shard tallies must accumulate, or the last shard silently wins."""
    manifest_path = _multipart_manifest(sample_source, tmp_path / "art", parts=3)
    manifest = materialize(None, tmp_path / "out", source_manifest=manifest_path)

    expected: dict[str, int] = {}
    catalog_paths = resolve_filing_catalog_paths(tmp_path / "out")
    snapshot_dir = catalog_paths.snapshot_dir(str(manifest["catalog_id"]))
    for part in manifest["parts"]:
        with duckdb.connect() as con:
            rows = con.execute(
                f"SELECT form, count(*) FROM read_parquet("
                f"'{snapshot_dir / part['path']}') WHERE form IS NOT NULL "
                "GROUP BY form"
            ).fetchall()
        for form, count in rows:
            expected[form] = expected.get(form, 0) + int(count)
    assert manifest["form_counts"] == expected


def test_manifest_records_that_shards_are_not_globally_sorted(
    catalog_snapshot: tuple[dict[str, Any], Path],
) -> None:
    """Each shard is sorted, but shards concatenate in overlapping chunk order."""
    manifest, _ = catalog_snapshot
    assert manifest["sort_order"] == "source_part_order"


def test_each_shard_is_sorted_by_the_projection_key(
    published_target_files: list[Path],
) -> None:
    for path in published_target_files:
        keys = [
            (row["source_cik"], row["accession"], row["document_path"])
            for row in pq.read_table(path).to_pylist()
        ]
        assert keys == sorted(keys), f"{path.name} is not ordered"


def test_a_cik_split_across_source_parts_is_refused(
    tmp_path: Path, sample_source: Path
) -> None:
    """Dedup is per shard, so a CIK spanning two parts must be refused, not repaired."""
    table = pq.read_table(sample_source)
    # The fixture's re-fetched registrant: one row per part, spanning the boundary.
    repeated = "0000320193"
    rows = table.to_pylist()
    keep = [i for i, row in enumerate(rows) if row["cik"] == repeated]
    rest = [i for i, row in enumerate(rows) if row["cik"] != repeated]
    assert len(keep) == 2, "fixture no longer carries a re-fetched registrant"

    payload = tmp_path / "art" / "snapshots" / "snap-split"
    parts_dir = payload / "parts"
    parts_dir.mkdir(parents=True)
    entries = []
    for index, offsets in enumerate([rest + keep[:1], keep[1:]]):
        path = parts_dir / f"part-{index:05d}.parquet"
        pq.write_table(table.take(pa.array(offsets, type=pa.int64())), path)
        entries.append(
            {
                "path": f"parts/{path.name}",
                "part_index": index,
                "source": f"chunk:{index}",
                "row_count": len(offsets),
                "byte_count": path.stat().st_size,
                "sha256": file_sha256(path),
                "schema_version": SOURCE_SCHEMA_VERSION,
            }
        )
    manifest_path = payload / "metadata.manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": "2.0.0",
                "snapshot_id": "snap-split",
                "output_path": "",
                "artifact_sha256": "",
                "row_count": table.num_rows,
                "part_count": len(entries),
                "parts": entries,
                "schema_version": SOURCE_SCHEMA_VERSION,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CatalogError, match="share CIKs"):
        materialize(None, tmp_path / "out", source_manifest=manifest_path)


def test_published_targets_match_the_declared_schema(
    published_targets: pa.Table,
) -> None:
    assert published_targets.schema.names == TARGET_SCHEMA.names


def test_published_profiles_match_the_declared_schema(
    published_profiles: pa.Table,
) -> None:
    assert published_profiles.schema.names == PROFILE_SCHEMA.names


def test_published_target_rows_match_the_oracle(published_targets: pa.Table) -> None:
    expected = _expected_targets()
    assert published_targets.num_rows == len(expected)
    for row, want in zip(published_targets.to_pylist(), expected):
        for column in TARGET_COLUMNS:
            assert _coerce(column, row[column]) == _coerce(column, want[column]), (
                f"{column} disagreed for occurrence {row['occurrence_id']}"
            )


def test_profiles_are_deduplicated_and_sorted(published_profiles: pa.Table) -> None:
    ciks = published_profiles.column("cik").to_pylist()
    assert len(ciks) == len(set(ciks))
    assert ciks == sorted(ciks)


def test_upstream_status_is_inherited_not_reinvented(
    published_profiles: pa.Table,
) -> None:
    statuses = set(published_profiles.column("status").to_pylist())
    assert {"ok", "partial", "failed"} <= statuses


def test_manifest_records_counts_and_lineage(
    catalog_snapshot: tuple[dict[str, Any], Path],
) -> None:
    manifest, _ = catalog_snapshot
    assert manifest["manifest_kind"] == "filing_catalog_snapshot"
    assert manifest["target_row_count"] == 13
    assert manifest["profile_row_count"] == 6
    assert manifest["target_columns"] == list(TARGET_COLUMNS)
    assert sum(manifest["form_counts"].values()) == manifest["target_row_count"]
    assert manifest["parts"][0]["row_count"] == manifest["target_row_count"]


# --- domain invariants ----------------------------------------------------


def test_fanout_is_retained_as_separate_occurrences(
    published_targets: pa.Table,
) -> None:
    """Distinct primary documents keep distinct keys; a shared bundle collapses."""
    rows = published_targets.to_pylist()
    by_accessor: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_accessor.setdefault(row["accession"], []).append(row)
    shared = {
        accession: grouped
        for accession, grouped in by_accessor.items()
        if len({r["source_cik"] for r in grouped}) > 1
    }
    assert shared, "expected a multi-registrant accession"

    for grouped in shared.values():
        assert len({r["occurrence_id"] for r in grouped}) == len(grouped)

    collapsed = [
        g for g in shared.values() if len({r["document_locator_key"] for r in g}) == 1
    ]
    assert collapsed, "expected a shared bundle document to collapse to one locator"

    distinct = [
        g
        for g in shared.values()
        if all(r["document_path_source"] == "primary_document" for r in g)
    ]
    assert distinct, "expected co-filers with distinct primary documents"
    for grouped in distinct:
        assert len({r["document_locator_key"] for r in grouped}) == len(grouped)


def test_occurrences_are_unique_across_the_snapshot(
    published_targets: pa.Table,
) -> None:
    ids = published_targets.column("occurrence_id").to_pylist()
    assert len(ids) == len(set(ids))


def test_targets_are_ordered_by_the_projection_key(published_targets: pa.Table) -> None:
    keys = [
        (r["source_cik"], r["accession"], r["document_path"])
        for r in published_targets.to_pylist()
    ]
    assert keys == sorted(keys)


def test_bundle_fallback_uses_the_raw_accession(
    published_targets: pa.Table,
) -> None:
    fallback = [
        r
        for r in published_targets.to_pylist()
        if r["document_path_source"] == "submission_bundle"
    ]
    assert fallback
    for row in fallback:
        assert "-" in row["document_path"], "bundle path keeps the hyphenated form"
        assert "-" not in row["accession"], "accession column is unhyphenated"
        assert not row["primary_document"].strip()


def test_archive_url_agrees_with_the_phase1_engine(
    published_targets: pa.Table,
) -> None:
    """The SQL fallback must build the same URL ``build_archive_url`` would."""
    from edgar_sec.engine.submissions.helpers import build_archive_url

    for row in published_targets.to_pylist():
        assert f"/{row['source_cik'].lstrip('0')}/" in row["archive_url"]
        if row["document_path_source"] == "primary_document":
            expected, _reason = build_archive_url(
                row["source_cik"], row["accession"], row["primary_document"]
            )
            assert row["archive_url"] == expected


def test_null_size_and_xbrl_flags_are_coalesced(
    published_targets: pa.Table,
) -> None:
    for row in published_targets.to_pylist():
        assert row["reported_size"] is not None
        for column in _BOOL_COLUMNS:
            assert isinstance(row[column], bool)


def test_materialization_is_deterministic(tmp_path: Path, sample_source: Path) -> None:
    first = materialize(sample_source, tmp_path / "a")
    second = materialize(sample_source, tmp_path / "b")
    assert first["catalog_id"] == second["catalog_id"]
    assert first["source_sha256"] == second["source_sha256"]
    assert first["target_row_count"] == second["target_row_count"]


def test_materialize_publishes_to_dag_catalog(
    tmp_path: Path, sample_source: Path
) -> None:
    """A materialization records in DAGCatalog with targets and profiles."""
    art_root = tmp_path / "art"
    result = materialize(sample_source, art_root)
    catalog = DAGCatalog(resolve_filing_catalog_paths(art_root).snapshots_root)
    assert catalog.has_snapshot(result["catalog_id"])
    manifest = catalog.get_manifest(result["catalog_id"])
    assert manifest is not None
    assert manifest.kind == "checkpoint"
    assert "filing_targets" in manifest.relations
    assert "company_profiles" in manifest.relations
    assert manifest.lineage_depth == 0


def test_delta_materialize_anti_joins_existing_and_emits_new_filings(
    tmp_path: Path, sample_source: Path
) -> None:
    """Delta materialization anti-joins base occurrences and emits net-new."""
    art_root = tmp_path / "art"
    base_res = materialize(sample_source, art_root)
    base_id = base_res["catalog_id"]

    full_table = pq.read_table(sample_source)
    pylist = full_table.to_pylist()
    refreshed_cik = pylist[0].copy()
    existing_filings = list(refreshed_cik["filings"])
    new_filing = existing_filings[0].copy()
    new_filing["accession_number"] = "0000000001-99-999999"
    new_filing["filing_date"] = "2026-01-01"
    new_filing["primary_document"] = "new_doc.htm"
    refreshed_cik["filings"] = existing_filings + [new_filing]

    brand_new = pylist[0].copy()
    brand_new["cik"] = "9999999999"
    brand_new_filing = existing_filings[0].copy()
    brand_new_filing["accession_number"] = "0000000002-99-999999"
    brand_new_filing["primary_document"] = "brand_new.htm"
    brand_new["filings"] = [brand_new_filing]

    delta_table = pa.Table.from_pylist(
        [refreshed_cik, brand_new], schema=full_table.schema
    )
    delta_part = tmp_path / "delta.parquet"
    pq.write_table(delta_table, delta_part)

    delta_manifest = tmp_path / "delta.manifest.json"
    delta_manifest.write_text(
        json.dumps(
            {
                "snapshot_id": "snap-delta",
                "parent_snapshot_id": base_id,
                "parts": [
                    {
                        "path": str(delta_part),
                        "sha256": file_sha256(delta_part),
                        "row_count": 2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    materialize(None, art_root, source_manifest=delta_manifest)
    catalog = DAGCatalog(resolve_filing_catalog_paths(art_root).snapshots_root)
    assert catalog.has_snapshot("snap-delta")
    node = catalog.get_manifest("snap-delta")
    assert node is not None
    assert node.kind == "delta"
    assert node.parents[0].snapshot_id == base_id
    assert node.checkpoint_anchor_id == base_id
    assert node.lineage_depth == 1

    delta_part_path = (
        resolve_filing_catalog_paths(art_root).snapshots_root
        / node.relations["filing_targets"][0].path
    )
    delta_targets = pq.read_table(delta_part_path).to_pylist()
    assert len(delta_targets) == 2
    emitted_docs = {r["document_path"] for r in delta_targets}
    assert emitted_docs == {"new_doc.htm", "brand_new.htm"}
