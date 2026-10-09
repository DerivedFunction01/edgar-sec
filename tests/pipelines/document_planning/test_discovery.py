from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.pipelines.document_planning.discovery import (
    DocumentPlanError,
    discover_document_plans,
    read_published_plan,
)
from edgar_sec.pipelines.document_planning.paths import resolve_document_planning_paths
from edgar_sec.pipelines.document_planning.schemas import (
    MATCHER_VERSION,
    TARGET_SCHEMA_VERSION,
)


def _publish_empty_manifest(tmp_path: Path):
    paths = resolve_document_planning_paths(tmp_path, tmp_path / "artifacts")
    identity = {
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "matcher_version": MATCHER_VERSION,
        "profile_digest": "a" * 64,
        "catalog_plan_id": "catalog-plan",
        "catalog_plan_digest": "b" * 64,
        "inventory_snapshot_id": None,
        "inventory_snapshot_digest": None,
    }
    plan_id = f"dplan_{sha256_text(canonical_json(identity))[:32]}"
    manifest = {
        "plan_id": plan_id,
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "matcher_version": MATCHER_VERSION,
        "profile_id": "primary",
        "profile_schema_version": "1",
        "profile_version": "1",
        "profile_digest": identity["profile_digest"],
        "catalog_plan_id": identity["catalog_plan_id"],
        "catalog_plan_digest": identity["catalog_plan_digest"],
        "inventory_snapshot_id": None,
        "inventory_snapshot_digest": None,
        "plan_identity": identity,
        "target_row_count": 0,
        "status_counts": {},
        "origin_counts": {},
        "reason_counts": {},
        "distinct_accession_coverage": {
            "catalog_scope": 0,
            "inventory_indexed": None,
            "inventory_unindexed": None,
            "matched": 0,
        },
        "parts": [],
    }
    manifest["plan_digest"] = canonical_hash(manifest)
    paths.plan_dir(plan_id).mkdir(parents=True)
    atomic_write_json(paths.plan_manifest_path(plan_id), manifest)
    return paths, plan_id


def test_plan_discovery_reads_manifests_without_opening_target_parts(
    tmp_path: Path,
) -> None:
    paths, plan_id = _publish_empty_manifest(tmp_path)
    rogue_part = paths.plan_dir(plan_id) / "targets" / "extra.parquet"
    rogue_part.parent.mkdir()
    rogue_part.write_bytes(b"not a parquet file")

    found = discover_document_plans(paths)

    assert found[0].plan_id == plan_id
    assert found[0].plan is not None
    with pytest.raises(DocumentPlanError, match="undeclared"):
        read_published_plan(plan_id, paths)


def test_plan_manifest_tampering_fails_integrity_check(tmp_path: Path) -> None:
    paths, plan_id = _publish_empty_manifest(tmp_path)
    path = paths.plan_manifest_path(plan_id)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["target_row_count"] = 1
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(DocumentPlanError, match="digest mismatch"):
        read_published_plan(plan_id, paths)
