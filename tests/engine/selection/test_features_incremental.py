"""Tests for incremental selection feature snapshots."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.filing_catalog.schemas import (
    LOCATOR_FEATURE_COLUMNS,
    OCCURRENCE_FEATURE_COLUMNS,
)
from edgar_sec.engine.selection.features import (
    FEATURE_SCHEMA_VERSION,
    FeatureSnapshotBuilder,
)
from edgar_sec.engine.selection.snapshot import feature_branch_name
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.duckdb import connect
from tests.engine.selection.features_support import (
    PROFILE_ROW,
    co_filed,
    make_policy,
    profile_row,
    make_snapshot,
    write_profiles,
    write_targets,
)


def test_each_snapshot_file_matches_its_declared_column_tuple(
    tmp_path: Path,
) -> None:
    """The tuples are the contract `source.py` selects out of. If the writer drifts
    from them, a reader selects a column the file does not have.
    """
    snapshot = make_snapshot(tmp_path, [{"source_cik": "0000000001"}])
    with connect() as con:
        occurrence_names = [
            description[0]
            for description in con.execute(
                f"SELECT * FROM {snapshot.occurrence_relation} LIMIT 0"
            ).description
        ]
    assert occurrence_names == list(OCCURRENCE_FEATURE_COLUMNS)
    assert pq.read_schema(snapshot.locator_features).names == list(
        LOCATOR_FEATURE_COLUMNS
    )


def test_delta_snapshot_reuses_independent_parent_parts(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    parent_root = write_targets(
        artifacts_root / "parent" / "filing_targets",
        [{"source_cik": "0000000001", "document_locator_key": "shared"}],
    )
    child_root = write_targets(
        artifacts_root / "child" / "filing_targets",
        [
            {
                "source_cik": "0000000002",
                "occurrence_id": "occ-0000",
                "document_locator_key": "shared",
            }
        ],
    )
    parent_part = parent_root / "part-00000.parquet"
    delta_part = child_root / "part-00000.parquet"
    parent_profiles = write_profiles(
        artifacts_root / "parent_profiles.parquet", [PROFILE_ROW]
    )
    child_profiles = write_profiles(
        artifacts_root / "child_profiles.parquet",
        [PROFILE_ROW, profile_row("0000000002")],
    )
    parent = FeatureSnapshotBuilder(
        parent_root, parent_profiles, artifacts_root, make_policy()
    ).build()

    child = FeatureSnapshotBuilder(
        child_root,
        child_profiles,
        artifacts_root,
        make_policy(),
        parent_feature_snapshot_id=parent.snapshot_dir.name,
        active_target_parts=[parent_part, delta_part],
        delta_target_parts=[delta_part],
    ).build()

    manifest = child.manifest
    assert manifest["incremental"] is True
    assert manifest["counts"]["independent_occurrence_rows"] == 1
    assert manifest["counts"]["locator_band_rows"] == 1
    assert manifest["counts"]["lifecycle_rows"] == 1
    assert manifest["counts"]["locator_features"] == 1
    assert len(child.occurrence_parts) == 2
    with connect() as con:
        occurrences, locator_class = con.execute(
            f"SELECT COUNT(*), MIN(locator_class) FROM {child.occurrence_relation} "
            f"JOIN read_parquet('{child.locator_features}') USING "
            "(document_locator_key)"
        ).fetchone()
    assert occurrences == 2
    assert locator_class == "low_2_to_3"
    with connect() as con:
        representative = con.execute(
            f"SELECT representative_cik FROM {child.locator_relation} "
            "WHERE document_locator_key = 'shared'"
        ).fetchone()[0]
    assert representative == "0000000002"


@pytest.mark.parametrize(("parent_size", "delta_size"), [(100, 5000), (5000, 100)])
def test_incremental_locator_filter_handles_delta_sizes_in_either_batch_order(
    tmp_path: Path, parent_size: int, delta_size: int
) -> None:
    artifacts_root = tmp_path / "artifacts"

    def rows(start: int, count: int) -> list[dict[str, Any]]:
        return [
            {
                "occurrence_id": f"occ-{index:05d}",
                "document_locator_key": f"0000000001/2021/doc-{index:05d}.htm",
                "accession": f"0000000001-21-{index:06d}",
            }
            for index in range(start, start + count)
        ]

    parent_root = write_targets(
        artifacts_root / "parent" / "filing_targets", rows(0, parent_size)
    )
    delta_root = write_targets(
        artifacts_root / "delta" / "filing_targets",
        rows(parent_size, delta_size),
    )
    parent_part = parent_root / "part-00000.parquet"
    delta_part = delta_root / "part-00000.parquet"
    profiles = write_profiles(artifacts_root / "profiles.parquet", [PROFILE_ROW])
    parent = FeatureSnapshotBuilder(
        parent_root, profiles, artifacts_root, make_policy()
    ).build()
    child = FeatureSnapshotBuilder(
        delta_root,
        profiles,
        artifacts_root,
        make_policy(),
        parent_feature_snapshot_id=parent.snapshot_dir.name,
        active_target_parts=[parent_part, delta_part],
        delta_target_parts=[delta_part],
    ).build()

    assert child.manifest["incremental"] is True
    assert child.manifest["counts"]["independent_occurrence_rows"] == delta_size
    with connect() as con:
        total_occurrences = con.execute(
            f"SELECT COUNT(*) FROM {child.occurrence_relation}"
        ).fetchone()[0]
        total_locators = con.execute(
            f"SELECT COUNT(*) FROM {child.locator_relation}"
        ).fetchone()[0]
    assert total_occurrences == parent_size + delta_size
    assert total_locators == parent_size + delta_size


def test_profile_change_for_inherited_cik_forces_full_independent_rebuild(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / "artifacts"
    parent_root = write_targets(artifacts_root / "parent", [{}])
    child_root = write_targets(
        artifacts_root / "child",
        [{"occurrence_id": "occ-child", "document_locator_key": "child"}],
    )
    parent_profile = write_profiles(
        artifacts_root / "parent_profiles.parquet", [PROFILE_ROW]
    )
    changed = profile_row(
        PROFILE_ROW["cik"], identity={"name": "Changed Co", "former_names": []}
    )
    child_profile = write_profiles(artifacts_root / "child_profiles.parquet", [changed])
    parent_part = parent_root / "part-00000.parquet"
    delta_part = child_root / "part-00000.parquet"
    parent = FeatureSnapshotBuilder(
        parent_root, parent_profile, artifacts_root, make_policy()
    ).build()

    child = FeatureSnapshotBuilder(
        child_root,
        child_profile,
        artifacts_root,
        make_policy(),
        parent_feature_snapshot_id=parent.snapshot_dir.name,
        active_target_parts=[parent_part, delta_part],
        delta_target_parts=[delta_part],
    ).build()

    manifest = child.manifest
    assert manifest["incremental"] is False
    assert len(child.occurrence_parts) == 1
    assert manifest["counts"]["independent_occurrence_rows"] == 2


def test_size_anchor_change_overrides_all_locator_bands_in_the_family(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / "artifacts"
    parent_root = write_targets(
        artifacts_root / "parent",
        [
            {
                "occurrence_id": "occ-a",
                "accession": "acc-a",
                "source_cik": "0000000001",
                "document_locator_key": "a",
                "reported_size": 100,
            },
            {
                "occurrence_id": "occ-b",
                "accession": "acc-b",
                "source_cik": "0000000002",
                "document_locator_key": "b",
                "reported_size": 1000,
            },
            {
                "occurrence_id": "occ-c",
                "accession": "acc-c",
                "source_cik": "0000000003",
                "document_locator_key": "c",
                "reported_size": 2000,
            },
        ],
    )
    child_root = write_targets(
        artifacts_root / "child",
        [
            {
                "occurrence_id": "occ-d",
                "accession": "acc-d",
                "source_cik": "0000000004",
                "document_locator_key": "d",
                "reported_size": 1,
            },
            {
                "occurrence_id": "occ-e",
                "accession": "acc-e",
                "source_cik": "0000000005",
                "document_locator_key": "e",
                "reported_size": 2,
            },
        ],
    )
    profiles = write_profiles(artifacts_root / "profiles.parquet", [PROFILE_ROW])
    parent_part = parent_root / "part-00000.parquet"
    delta_part = child_root / "part-00000.parquet"
    parent = FeatureSnapshotBuilder(
        parent_root, profiles, artifacts_root, make_policy()
    ).build()
    child = FeatureSnapshotBuilder(
        child_root,
        profiles,
        artifacts_root,
        make_policy(),
        parent_feature_snapshot_id=parent.snapshot_dir.name,
        active_target_parts=[parent_part, delta_part],
        delta_target_parts=[delta_part],
    ).build()

    with connect() as con:
        parent_band = con.execute(
            "SELECT size_band FROM "
            f"{parent.occurrence_relation} WHERE document_locator_key = 'b'"
        ).fetchone()[0]
        child_band = con.execute(
            "SELECT size_band FROM "
            f"{child.occurrence_relation} WHERE document_locator_key = 'b'"
        ).fetchone()[0]
    assert parent_band == "median"
    assert child_band == "large"
    assert len(child.locator_band_parts) == 2

    cold = FeatureSnapshotBuilder(
        child_root,
        profiles,
        tmp_path / "cold",
        make_policy(),
        active_target_parts=[parent_part, delta_part],
    ).build()
    with connect() as con:
        incremental_rows = con.execute(
            f"SELECT * FROM {child.occurrence_relation} ORDER BY occurrence_id"
        ).fetchall()
        cold_rows = con.execute(
            f"SELECT * FROM {cold.occurrence_relation} ORDER BY occurrence_id"
        ).fetchall()
        incremental_locators = con.execute(
            f"SELECT * FROM {child.locator_relation} ORDER BY document_locator_key"
        ).fetchall()
        cold_locators = con.execute(
            f"SELECT * FROM {cold.locator_relation} ORDER BY document_locator_key"
        ).fetchall()
    assert incremental_rows == cold_rows
    assert incremental_locators == cold_locators


def test_global_max_advance_rebuilds_all_lifecycle_and_locator_rows(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / "artifacts"
    parent_root = write_targets(artifacts_root / "parent", [{}])
    child_root = write_targets(
        artifacts_root / "child",
        [
            {
                "source_cik": "0000000002",
                "occurrence_id": "occ-new-year",
                "document_locator_key": "new-year",
                "report_date": "2026-12-31",
            }
        ],
    )
    profiles = write_profiles(artifacts_root / "profiles.parquet", [PROFILE_ROW])
    parent_part = parent_root / "part-00000.parquet"
    delta_part = child_root / "part-00000.parquet"
    parent = FeatureSnapshotBuilder(
        parent_root, profiles, artifacts_root, make_policy()
    ).build()
    child = FeatureSnapshotBuilder(
        child_root,
        profiles,
        artifacts_root,
        make_policy(),
        parent_feature_snapshot_id=parent.snapshot_dir.name,
        active_target_parts=[parent_part, delta_part],
        delta_target_parts=[delta_part],
    ).build()

    manifest = child.manifest
    assert manifest["incremental"] is True
    assert manifest["global_max_year"] == 2026
    assert manifest["counts"]["lifecycle_rows"] == 2
    assert manifest["counts"]["locator_features"] == 2


def test_new_years_recompute_lifecycle_only_for_touched_cik(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    parent_root = write_targets(
        artifacts_root / "parent",
        [
            {
                "occurrence_id": "occ-2010",
                "accession": "acc-2010",
                "source_cik": "0000000001",
                "document_locator_key": "doc-2010",
                "filing_date": "2011-03-01",
                "report_date": "2010-12-31",
            },
            {
                "occurrence_id": "occ-2014",
                "accession": "acc-2014",
                "source_cik": "0000000001",
                "document_locator_key": "doc-2014",
                "filing_date": "2015-03-01",
                "report_date": "2014-12-31",
            },
        ],
    )
    child_root = write_targets(
        artifacts_root / "child",
        [
            {
                "occurrence_id": f"occ-{year}",
                "accession": f"acc-{year}",
                "source_cik": "0000000001",
                "document_locator_key": f"doc-{year}",
                "filing_date": f"{year + 1}-03-01",
                "report_date": f"{year}-12-31",
            }
            for year in (2011, 2012, 2013)
        ],
    )
    profiles = write_profiles(artifacts_root / "profiles.parquet", [PROFILE_ROW])
    parent_part = parent_root / "part-00000.parquet"
    delta_part = child_root / "part-00000.parquet"
    parent = FeatureSnapshotBuilder(
        parent_root, profiles, artifacts_root, make_policy()
    ).build()
    child = FeatureSnapshotBuilder(
        child_root,
        profiles,
        artifacts_root,
        make_policy(),
        parent_feature_snapshot_id=parent.snapshot_dir.name,
        active_target_parts=[parent_part, delta_part],
        delta_target_parts=[delta_part],
    ).build()

    manifest = child.manifest
    assert manifest["global_max_year"] == 2014
    assert manifest["counts"]["lifecycle_rows"] == 1
    with connect() as con:
        parent_gap = con.execute(
            "SELECT has_revival_gap FROM "
            f"{parent.occurrence_relation} WHERE occurrence_id = 'occ-2010'"
        ).fetchone()[0]
        child_gap = con.execute(
            "SELECT has_revival_gap FROM "
            f"{child.occurrence_relation} WHERE occurrence_id = 'occ-2010'"
        ).fetchone()[0]
    assert parent_gap is True
    assert child_gap is False


def test_a_co_filed_document_is_classified_by_its_occurrence_count(
    tmp_path: Path,
) -> None:
    """`locator_class` counts a partition, so it has to be read before the ranking
    keeps one row per locator. Framed as an ordered window it would count to 1.
    """
    rows = [
        *co_filed(1, "alone"),
        *co_filed(2, "twice"),
        *co_filed(5, "five-times"),
    ]
    snapshot = make_snapshot(tmp_path, rows)
    with connect() as con:
        classified = dict(
            con.execute(
                "SELECT document_locator_key, locator_class "
                f"FROM read_parquet('{snapshot.locator_features}')"
            ).fetchall()
        )
    assert classified == {
        "alone": "single",
        "twice": "low_2_to_3",
        "five-times": "high_4_plus",
    }


def test_feature_schema_version_is_part_of_snapshot_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = make_snapshot(tmp_path, [{"source_cik": "0000000001"}])
    monkeypatch.setattr(
        "edgar_sec.engine.selection.features.FEATURE_SCHEMA_VERSION", "test-version"
    )
    second = make_snapshot(tmp_path, [{"source_cik": "0000000001"}])

    assert first.snapshot_dir != second.snapshot_dir
    assert first.manifest["feature_schema_version"] == FEATURE_SCHEMA_VERSION
    assert second.manifest["feature_schema_version"] == "test-version"
    catalog = DAGCatalog(second.snapshot_dir.parent)
    branch = feature_branch_name(second.manifest["feature_signature"])
    assert catalog.read_pointer(branch)["snapshot_id"] == second.snapshot_dir.name
