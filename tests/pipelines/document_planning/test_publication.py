from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.foundation.runtime.settings.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.pipelines.document_planning.discovery import DocumentPlanError
from edgar_sec.pipelines.document_planning.paths import resolve_document_planning_paths
from edgar_sec.pipelines.document_planning.publication import publish_plan_bundle
from edgar_sec.pipelines.document_planning.schemas import (
    MATCHER_VERSION,
    PLAN_BUNDLE_SCHEMA_VERSION,
    TARGET_SCHEMA_VERSION,
)


def _manifest(identity: dict[str, object], plan_id: str) -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "bundle_schema_version": PLAN_BUNDLE_SCHEMA_VERSION,
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "matcher_version": MATCHER_VERSION,
        "row_group_size": identity["row_group_size"],
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


def test_publication_atomically_reuses_only_identical_manifest(tmp_path: Path) -> None:
    paths = resolve_document_planning_paths(tmp_path, tmp_path / "artifacts")
    identity = {
        "bundle_schema_version": PLAN_BUNDLE_SCHEMA_VERSION,
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "matcher_version": MATCHER_VERSION,
        "row_group_size": DEFAULT_ROW_GROUP_SIZE,
        "profile_digest": "a" * 64,
        "catalog_plan_id": "catalog-1",
        "catalog_plan_digest": "b" * 64,
        "inventory_snapshot_id": None,
        "inventory_snapshot_digest": None,
    }
    plan_id = f"dplan_{sha256_text(canonical_json(identity))[:32]}"
    manifest = _manifest(identity, plan_id)
    first_stage = tmp_path / "first"
    first_stage.mkdir()
    first = publish_plan_bundle(plan_id, identity, manifest, first_stage, paths)
    second_stage = tmp_path / "second"
    second_stage.mkdir()
    second = publish_plan_bundle(plan_id, identity, manifest, second_stage, paths)

    assert first.plan_id == second.plan_id
    assert not first.reused
    assert second.reused
    assert first.root == paths.plan_dir(plan_id)
    assert first.manifest == second.manifest
    assert not first_stage.exists()
    assert second_stage.exists()


def test_publication_refuses_a_divergent_rerun(tmp_path: Path) -> None:
    paths = resolve_document_planning_paths(tmp_path, tmp_path / "artifacts")
    identity = {
        "bundle_schema_version": PLAN_BUNDLE_SCHEMA_VERSION,
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "matcher_version": MATCHER_VERSION,
        "row_group_size": DEFAULT_ROW_GROUP_SIZE,
        "profile_digest": "a" * 64,
        "catalog_plan_id": "catalog-1",
        "catalog_plan_digest": "b" * 64,
        "inventory_snapshot_id": None,
        "inventory_snapshot_digest": None,
    }
    plan_id = f"dplan_{sha256_text(canonical_json(identity))[:32]}"
    first_stage = tmp_path / "first"
    first_stage.mkdir()
    publish_plan_bundle(
        plan_id, identity, _manifest(identity, plan_id), first_stage, paths
    )
    changed = _manifest(identity, plan_id)
    changed["profile_version"] = "2"
    second_stage = tmp_path / "second"
    second_stage.mkdir()

    with pytest.raises(DocumentPlanError, match="payload or part digests diverge"):
        publish_plan_bundle(plan_id, identity, changed, second_stage, paths)
