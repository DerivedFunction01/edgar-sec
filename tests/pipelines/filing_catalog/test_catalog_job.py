"""Unit tests for filing-catalog materialization.

The oracle assertions here compare DuckDB output against the Milestone 0 CSV,
which was derived by an independent Python transcription of the same rules.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.filing_catalog.schemas import (
    PROFILE_SCHEMA,
    TARGET_COLUMNS,
    TARGET_SCHEMA,
)
from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.pipelines.filing_catalog.catalog_job import (
    CatalogError,
    materialize,
    resolve_source,
)
from tests.support import catalog_fixture_path

_BOOL_COLUMNS = {"is_amendment", "is_xbrl", "is_inline_xbrl", "is_xbrl_numeric"}


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


# --- the three load-bearing guards ----------------------------------------


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
    """Write the manifest Phase 1 publishes beside a snapshot payload."""
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
                "output_path": str(target),
                "artifact_sha256": file_sha256(target),
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

    source, handoff = resolve_source(None, manifest)

    assert source.suffix == ".parquet", "the JSON manifest was returned as the source"
    assert handoff is not None and handoff["snapshot_id"] == "snap-1"
    assert pq.read_schema(source).names == SUBMISSION_METADATA_SCHEMA.names


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
    payload = json.loads(manifest.read_text(encoding="utf-8"))["output_path"]
    table = pq.read_table(payload).drop_columns(["listings"])
    pq.write_table(table, payload)

    with pytest.raises(CatalogError, match="digest mismatch"):
        resolve_source(None, manifest)


def test_source_manifest_without_a_digest_is_refused(
    tmp_path: Path, sample_source: Path
) -> None:
    manifest = _phase1_manifest(sample_source, tmp_path / "art")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document.pop("artifact_sha256")
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(CatalogError, match="no artifact digest"):
        resolve_source(None, manifest)


def test_source_manifest_without_an_output_path_is_refused(
    tmp_path: Path, sample_source: Path
) -> None:
    manifest = _phase1_manifest(sample_source, tmp_path / "art")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document.pop("output_path")
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(CatalogError, match="names no output_path"):
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
    monkeypatch.setenv("EDGAR_ARTIFACTS_DIR", str(tmp_path))
    with pytest.raises(CatalogError, match="no Phase 1 snapshot"):
        resolve_source(None)


# --- published artifacts --------------------------------------------------


# This test intentionally spells the published names out as literals. It is the
# layout contract from phase_2.md 4.4, so a rename must fail here rather than
# being silently absorbed by a constant that both sides happen to share.
def test_snapshot_layout_matches_the_documented_contract(
    catalog_snapshot: tuple[dict[str, Any], Path],
) -> None:
    _, snapshot_dir = catalog_snapshot
    assert (snapshot_dir / "company_profiles.parquet").is_file()
    assert (snapshot_dir / "filing_targets" / "part-00000.parquet").is_file()
    assert (snapshot_dir / "snapshot.manifest.json").is_file()


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
    """One accession filed by two CIKs yields two occurrences.

    Two distinct fan-out shapes exist and both must survive. Co-filers with
    *different* primary documents are different documents, so they hold
    different locator keys. Co-filers that both fall back to the bundle resolve
    to the same ``<raw accession>.txt`` and therefore collapse to a single
    locator, which is the case selection dedup depends on.
    """
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
        # Fan-out is never collapsed: each registrant keeps its own occurrence.
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


def test_amendment_predicate_is_a_suffix_rule(published_targets: pa.Table) -> None:
    for row in published_targets.to_pylist():
        form = row["form"].upper()
        assert row["is_amendment"] is (form.endswith(("/A", "_A")))


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


def test_source_batch_size_is_validated(tmp_path: Path, sample_source: Path) -> None:
    with pytest.raises(ValueError, match="source_batch_size must be >= 1"):
        materialize(sample_source, tmp_path / "out", source_batch_size=0)


def test_materialization_is_deterministic(tmp_path: Path, sample_source: Path) -> None:
    first = materialize(sample_source, tmp_path / "a")
    second = materialize(sample_source, tmp_path / "b")
    assert first["catalog_id"] == second["catalog_id"]
    assert first["source_sha256"] == second["source_sha256"]
    assert first["target_row_count"] == second["target_row_count"]
