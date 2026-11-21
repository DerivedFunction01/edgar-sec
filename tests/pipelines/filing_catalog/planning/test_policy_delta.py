"""A catalog delta reusing its parent plan's selection features."""

from __future__ import annotations

import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.filing_catalog.schemas import (
    PROFILE_SCHEMA_VERSION,
    TARGET_SCHEMA,
    TARGET_SCHEMA_VERSION,
)
from edgar_sec.engine.selection.snapshot import load_snapshot_paths
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
    ordered_parts_fingerprint,
)
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.filing_catalog.paths import (
    SNAPSHOT_FILE,
    TARGETS_DIR,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planning.policy import plan_policy
from tests.pipelines.filing_catalog.planning.policy_support import _policy


def test_policy_plan_reuses_parent_features_for_a_catalog_delta(
    catalog_snapshot: tuple[dict[str, object], Path],
    published_target_files: list[Path],
    catalog_artifacts_root: Path,
) -> None:
    parent_metadata, _ = catalog_snapshot
    parent_id = str(parent_metadata["catalog_id"])
    paths = resolve_filing_catalog_paths(catalog_artifacts_root)
    policy = _policy()
    plan_policy(parent_id, policy, catalog_artifacts_root)

    dag = DAGCatalog(paths.snapshots_root)
    parent_node = dag.get_manifest(parent_id)
    assert parent_node is not None
    parent_manifest_digest = dag.get_manifest_sha256(parent_id)
    assert parent_manifest_digest

    child_id = "thin-policy-delta"
    child_dir = paths.snapshot_dir(child_id)
    targets_dir = paths.snapshot_targets_dir(child_id)
    targets_dir.mkdir(parents=True)
    source_rows = [
        row
        for part in published_target_files
        for row in pq.read_table(part).to_pylist()
        if row["form"] == "10-K"
    ]
    assert source_rows
    child_row = dict(source_rows[0])
    child_row.update(
        occurrence_id="occurrence-thin-delta",
        document_locator_key="locator-thin-delta",
        source_cik="9999999999",
        accession="0000000002-20-000001",
        primary_document="thin-delta.htm",
        document_path="thin-delta.htm",
        archive_url="https://www.sec.gov/Archives/edgar/data/2/thin-delta.htm",
    )
    target_part = targets_dir / "part-00000.parquet"
    pq.write_table(pa.Table.from_pylist([child_row], schema=TARGET_SCHEMA), target_part)

    parent_profile = paths.snapshot_profiles_file(parent_id)
    child_profile = paths.snapshot_profiles_file(child_id)
    child_profile.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(parent_profile, child_profile)

    target_digest = file_sha256(target_part)
    profile_digest = file_sha256(child_profile)
    target_descriptor = PartDescriptor(
        path=f"{child_id}/{TARGETS_DIR}/{target_part.name}",
        sha256=target_digest,
        row_count=1,
        byte_size=target_part.stat().st_size,
    )
    profile_descriptor = PartDescriptor(
        path=f"{child_id}/{SNAPSHOT_FILE}",
        sha256=profile_digest,
        row_count=pq.read_metadata(child_profile).num_rows,
        byte_size=child_profile.stat().st_size,
    )
    dag.record_node(
        DAGNodeManifest(
            snapshot_id=child_id,
            kind="delta",
            parents=(
                ParentRef(
                    snapshot_id=parent_id,
                    manifest_sha256=parent_manifest_digest,
                ),
            ),
            checkpoint_anchor_id=parent_node.checkpoint_anchor_id,
            lineage_depth=parent_node.lineage_depth + 1,
            created_at="2026-10-11T00:00:00+00:00",
            relations={
                "filing_targets": (target_descriptor,),
                "company_profiles": (profile_descriptor,),
            },
            logical_fingerprint=ordered_parts_fingerprint([target_digest]),
            schema_versions={
                "filing_targets": TARGET_SCHEMA_VERSION,
                "company_profiles": PROFILE_SCHEMA_VERSION,
            },
            metadata={"source_artifact": "test-delta"},
        )
    )

    plan_policy(child_id, policy, catalog_artifacts_root)

    feature_manifests = []
    for row in dag.list_snapshots():
        feature_node = dag.get_manifest(row["snapshot_id"])
        if (
            feature_node is not None
            and feature_node.metadata.get("artifact_kind") == "selection_features"
        ):
            feature_manifests.append(
                load_snapshot_paths(
                    paths.snapshots_root / feature_node.snapshot_id
                ).manifest
            )
    child_features = [
        value
        for value in feature_manifests
        if value.get("profile_path") == str(child_profile.resolve())
    ]
    assert len(child_features) == 1
    assert child_features[0]["incremental"] is True
    assert child_features[0]["counts"]["independent_occurrence_rows"] == 1
    snapshot = load_snapshot_paths(
        paths.snapshots_root / child_features[0]["snapshot_id"]
    )
    with connect() as con:
        child_rows = con.execute(
            f"SELECT COUNT(*) FROM {snapshot.occurrence_relation}"
        ).fetchone()[0]
    parent_features = next(
        value
        for value in feature_manifests
        if value.get("profile_path") == str(parent_profile.resolve())
    )
    parent_snapshot = load_snapshot_paths(
        paths.snapshots_root / parent_features["snapshot_id"]
    )
    with connect() as con:
        parent_rows = con.execute(
            f"SELECT COUNT(*) FROM {parent_snapshot.occurrence_relation}"
        ).fetchone()[0]
    assert child_rows == parent_rows + 1
