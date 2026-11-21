"""Tests for building a selection feature snapshot from the catalog."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edgar_sec.domain.filing_catalog.schemas import TARGET_COLUMNS
from edgar_sec.engine.selection.features import (
    IDENTITY_COLUMNS,
    FeatureSnapshotBuilder,
)
from edgar_sec.engine.selection.policy import EraBand, SelectionPolicy
from edgar_sec.engine.selection.snapshot import SnapshotPaths, feature_branch_name
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.working.retention import analyze_retention
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.filing_catalog.catalog_job import materialize
from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths
from tests.engine.selection.features_support import (
    PROFILE_ROW,
    make_builder,
    make_policy,
    profile_row,
    write_profiles,
    write_targets,
)
from tests.support.rosters import era_submission_metadata


def test_identity_columns_track_the_target_schema() -> None:
    """The projection is derived from the domain schema, not restated. A new
    target column must reach the snapshot without a second list to edit.
    """
    projected = [column.strip() for column in IDENTITY_COLUMNS.split(",")]
    assert projected == [c for c in TARGET_COLUMNS if c != "document_path_source"]


def test_builder_rejects_impossible_options() -> None:
    with pytest.raises(ValueError, match="gap_years must be at least 2"):
        FeatureSnapshotBuilder("t", "p", "o", make_policy(), gap_years=1)
    with pytest.raises(ValueError, match="cessation_grace_years must be at least 1"):
        FeatureSnapshotBuilder("t", "p", "o", make_policy(), cessation_grace_years=0)
    with pytest.raises(ValueError, match="stub_size_threshold must be at least 1"):
        FeatureSnapshotBuilder("t", "p", "o", make_policy(), stub_size_threshold=0)


def test_snapshot_dir_is_content_addressed(tmp_path: Path) -> None:
    profile_path = write_profiles(tmp_path / "p.parquet", [PROFILE_ROW])
    builder = make_builder(tmp_path, tmp_path / "t", profile_path)
    first = builder.snapshot_dir(["10-K"])
    assert first == builder.snapshot_dir(["10-K"])
    assert first != builder.snapshot_dir(["10-Q"])

    other_policy = SelectionPolicy(
        corpus_id="other", forms=["10-K"], base_content_units=1
    )
    other = FeatureSnapshotBuilder(
        builder.target_root, builder.profile_path, builder.output_root, other_policy
    )
    assert other.snapshot_dir(["10-K"]) != first


def test_snapshot_identity_changes_when_profile_content_changes(tmp_path: Path) -> None:
    target_root = write_targets(tmp_path / "targets", [{}])
    profile_path = write_profiles(tmp_path / "profiles.parquet", [PROFILE_ROW])
    builder = make_builder(tmp_path, target_root, profile_path)
    original = builder.snapshot_dir(["10-K"])
    changed = profile_row(
        PROFILE_ROW["cik"], identity={"name": "Changed Co", "former_names": []}
    )
    write_profiles(profile_path, [changed])

    assert builder.snapshot_dir(["10-K"]) != original


def test_builds_a_feature_snapshot_from_the_published_catalog(
    tmp_path: Path, sample_source: Path
) -> None:
    """The only place the policy's forms, the catalog targets, the registrant
    profiles, and company-family clustering meet.
    """
    artifacts_root = tmp_path / "artifacts"
    manifest = materialize(sample_source, artifacts_root)
    catalog_id = str(manifest["catalog_id"])
    paths = resolve_filing_catalog_paths(artifacts_root)

    builder = FeatureSnapshotBuilder(
        target_root=paths.snapshot_targets_dir(catalog_id),
        profile_path=paths.snapshot_profiles_file(catalog_id),
        output_root=artifacts_root,
        policy=make_policy(),
    )
    events: list[dict[str, Any]] = []
    snapshot = builder.build(progress=events.append)

    assert isinstance(snapshot, SnapshotPaths)
    stages = [event["stage"] for event in events]
    assert "feature_occurrences_started" in stages
    assert "feature_anchors_complete" in stages
    assert "feature_locator_bands_complete" in stages
    assert "feature_locator_features_complete" in stages
    assert snapshot.manifest["artifact_kind"] == "selection_features"
    assert not (snapshot.snapshot_dir / "feature_snapshot.json").exists()
    dag = DAGCatalog(snapshot.snapshot_dir.parent)
    assert dag.has_snapshot(snapshot.snapshot_dir.name)
    branch_name = feature_branch_name(snapshot.manifest["feature_signature"])
    assert dag.read_pointer(branch_name)["snapshot_id"] == snapshot.snapshot_dir.name
    assert (
        snapshot.snapshot_dir.name
        in analyze_retention(snapshot.snapshot_dir.parent).retained_snapshots
    )
    assert all(path.is_file() for path in snapshot.occurrence_parts)
    assert snapshot.locator_bands.is_file()
    assert snapshot.lifecycle.is_file()
    assert snapshot.locator_features.is_file()

    # Stage files are pure build scratch and must not survive.
    for scratch in ("occurrence_base",):
        assert not (snapshot.snapshot_dir / f"{scratch}.parquet").exists()

    with connect() as con:
        occurrences = con.execute(
            f"SELECT COUNT(*) FROM {snapshot.occurrence_relation}"
        ).fetchone()[0]
        locators = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{snapshot.locator_features}')"
        ).fetchone()[0]
        families = con.execute(
            "SELECT COUNT(DISTINCT company_family) FROM "
            f"read_parquet('{snapshot.locator_features}')"
        ).fetchone()[0]

    # The fixture also carries a 10-K/A; the form filter must exclude it.
    assert occurrences == 4
    assert locators == 4
    assert families > 1, "clustering collapsed distinct registrants into one family"


def test_primary_exhibit_feature_flows_into_policy_snapshot(
    tmp_path: Path,
) -> None:
    source = era_submission_metadata(tmp_path / "era-source.parquet")
    artifacts_root = tmp_path / "artifacts"
    manifest = materialize(source, artifacts_root)
    paths = resolve_filing_catalog_paths(artifacts_root)
    builder = FeatureSnapshotBuilder(
        target_root=paths.snapshot_targets_dir(str(manifest["catalog_id"])),
        profile_path=paths.snapshot_profiles_file(str(manifest["catalog_id"])),
        output_root=artifacts_root,
        policy=make_policy(),
    )

    snapshot = builder.build()
    with connect() as con:
        count = con.execute(
            f"SELECT COUNT(*) FROM {snapshot.locator_relation} "
            "WHERE primary_exhibit_like"
        ).fetchone()[0]

    assert count > 0


def test_era_falls_back_to_filing_date_when_report_date_is_empty(
    tmp_path: Path,
) -> None:
    source = era_submission_metadata(tmp_path / "era-source.parquet")
    artifacts_root = tmp_path / "artifacts"
    manifest = materialize(source, artifacts_root)
    paths = resolve_filing_catalog_paths(artifacts_root)
    policy = SelectionPolicy(
        corpus_id="test_corpus",
        forms=["10-K", "8-K"],
        era_bands=[
            EraBand(name="y2000_2002", start_year=2000, end_year=2003),
            EraBand(name="y2003_2005", start_year=2003, end_year=2006),
        ],
        base_content_units=2,
    )
    builder = FeatureSnapshotBuilder(
        target_root=paths.snapshot_targets_dir(str(manifest["catalog_id"])),
        profile_path=paths.snapshot_profiles_file(str(manifest["catalog_id"])),
        output_root=artifacts_root,
        policy=policy,
    )

    snapshot = builder.build()
    with connect() as con:
        rows = con.execute(
            f"SELECT accession, era FROM {snapshot.occurrence_relation} "
            "WHERE accession IN ('000032019302000123', '000132680104000077', "
            "'000165204401000011', '000001961705000045')"
        ).fetchall()

    # The appended fixture rows carry report_date="" (the Form 144 shape);
    # their eras must come from filing_date.
    assert rows
    assert {era for _, era in rows} <= {"y2000_2002", "y2003_2005"}
    by_accession = dict(rows)
    assert by_accession["000032019302000123"] == "y2000_2002"
    assert by_accession["000132680104000077"] == "y2003_2005"
    assert by_accession["000165204401000011"] == "y2000_2002"
    assert by_accession["000001961705000045"] == "y2003_2005"


def test_rebuilding_the_same_snapshot_reuses_the_published_one(
    tmp_path: Path, sample_source: Path
) -> None:
    """Content-addressing exists so a rerun skips the expensive half of selection."""
    artifacts_root = tmp_path / "artifacts"
    manifest = materialize(sample_source, artifacts_root)
    catalog_id = str(manifest["catalog_id"])
    paths = resolve_filing_catalog_paths(artifacts_root)

    builder = make_builder(
        artifacts_root,
        paths.snapshot_targets_dir(catalog_id),
        paths.snapshot_profiles_file(catalog_id),
    )
    first = builder.build()
    stamp = first.locator_features.stat().st_mtime_ns
    second = builder.build()

    assert second == first
    assert second.locator_features.stat().st_mtime_ns == stamp


def test_builder_reports_a_catalog_with_no_targets(tmp_path: Path) -> None:
    empty = tmp_path / "filing_targets"
    empty.mkdir()
    builder = FeatureSnapshotBuilder(
        empty, tmp_path / "p.parquet", tmp_path, make_policy()
    )
    with pytest.raises(FileNotFoundError, match="no target part files"):
        builder.build()
