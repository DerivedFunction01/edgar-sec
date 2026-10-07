"""Transient execution identity for catalog runs and its atomic validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.paths import ProjectPaths
from edgar_sec.pipelines.document_storage.catalog_plan import (
    CatalogPlan,
    CatalogPlanError,
)
from edgar_sec.pipelines.document_storage.paths import (
    DocumentStoragePaths,
    MANIFEST_FILE_NAME,
)
from edgar_sec.pipelines.document_storage.run_manifest import (
    RUN_MANIFEST_VERSION,
    CatalogRunIdentity,
    RunManifestError,
    catalog_run_identity,
    create_or_validate_manifest,
)
from edgar_sec.pipelines.document_storage.execution import WORKER_SCHEMA_VERSION

BODY = b"""\
SECURITIES AND EXCHANGE COMMISSION

FORM 10-K

ACME INDUSTRIAL WIDGETS, INC.

PART I

ITEM 1. Business

The Company was founded in 1994 and is a leading provider of industrial widgets. It
operates three manufacturing facilities and employs approximately 4,200 people.

SIGNATURES

/s/ Jane Q. Registrant
"""


@pytest.fixture
def paths(tmp_path: Path) -> DocumentStoragePaths:
    return DocumentStoragePaths(tmp_path / ".artifacts")


@pytest.fixture
def catalog_plan(era_plan_dir: Path) -> CatalogPlan:
    return CatalogPlan(era_plan_dir, chunk_size=3)


def _make_identity(
    catalog_plan: CatalogPlan,
    paths: ProjectPaths,
    mode: str,
    fixture_ids: tuple[str, ...],
) -> CatalogRunIdentity:
    from edgar_sec.pipelines.document_storage.processor import FilingProcessor

    return catalog_run_identity(
        catalog_plan,
        run_id="run-id",
        mode=mode,
        fixture_ids=fixture_ids,
        processor=FilingProcessor(),
    )


def test_a_run_manifest_records_plan_and_execution_inputs(
    paths: ProjectPaths, catalog_plan: CatalogPlan
) -> None:
    identity = _make_identity(catalog_plan, paths, "fixture", ("fix-a",))
    assert identity.values["run_id"] == "run-id"
    assert identity.values["plan"]["plan_id"] == catalog_plan.metadata.plan_id
    assert identity.values["plan"]["catalog_id"] == catalog_plan.metadata.catalog_id
    assert identity.values["plan"]["scope"] == catalog_plan.metadata.scope
    assert (
        identity.values["plan"]["selection_fingerprint"]
        == catalog_plan.metadata.selection_fingerprint
    )
    assert identity.values["locator_count"] == catalog_plan.metadata.locator_count
    assert identity.values["chunk_count"] == catalog_plan.chunk_count
    assert identity.values["work_order_version"] == "catalog-1"
    assert identity.values["chunk_size"] == catalog_plan.chunk_size
    assert identity.values["processor_fingerprint"] == "document-storage-normalizer:v2"
    assert identity.values["worker_schema_version"] == WORKER_SCHEMA_VERSION
    assert identity.values["fetch_mode"] == "fixture"
    assert identity.values["fixture_ids"] == ["fix-a"]
    source_paths = [source["path"] for source in identity.values["sources"]]
    assert source_paths[0] == "plan.json"
    assert source_paths[1] == "locator_groups.parquet"
    assert all(source["sha256"] for source in identity.values["sources"])
    assert source_paths.count("plan.json") == 1
    assert source_paths.count("locator_groups.parquet") == 1


def test_a_run_manifest_is_created_atomically(
    paths: ProjectPaths, catalog_plan: CatalogPlan
) -> None:
    identity = _make_identity(catalog_plan, paths, "fixture", ("fix-a",))
    mode = create_or_validate_manifest(paths.run_dir("run-new"), "run-new", identity)
    assert mode == "fresh"
    assert (paths.run_dir("run-new") / MANIFEST_FILE_NAME).is_file()
    manifest = json.loads(
        (paths.run_dir("run-new") / MANIFEST_FILE_NAME).read_text(encoding="utf-8")
    )
    assert manifest["manifest_version"] == RUN_MANIFEST_VERSION
    assert manifest["run_id"] == "run-new"
    assert manifest["identity"] == identity.values


def test_a_resumed_run_reuses_a_matching_manifest(
    paths: ProjectPaths, catalog_plan: CatalogPlan
) -> None:
    identity = _make_identity(catalog_plan, paths, "fixture", ("fix-a",))
    create_or_validate_manifest(paths.run_dir("run-resume"), "run-resume", identity)
    mode = create_or_validate_manifest(
        paths.run_dir("run-resume"), "run-resume", identity
    )
    assert mode == "resumed"


def test_a_mismatched_manifest_is_refused(
    paths: ProjectPaths, catalog_plan: CatalogPlan
) -> None:
    identity = _make_identity(catalog_plan, paths, "fixture", ("fix-a",))
    create_or_validate_manifest(paths.run_dir("run-mismatch"), "run-mismatch", identity)
    with pytest.raises(RunManifestError, match="does not match current inputs"):
        create_or_validate_manifest(
            paths.run_dir("run-mismatch"),
            "run-mismatch",
            _make_identity(catalog_plan, paths, "live", ("fix-a",)),
        )
    with pytest.raises(RunManifestError, match="does not match current inputs"):
        create_or_validate_manifest(
            paths.run_dir("run-mismatch"),
            "run-mismatch",
            _make_identity(catalog_plan, paths, "fixture", ("fix-b",)),
        )


def test_a_missing_manifest_is_refused(
    paths: ProjectPaths, catalog_plan: CatalogPlan
) -> None:
    identity = _make_identity(catalog_plan, paths, "fixture", ("fix-a",))
    create_or_validate_manifest(
        paths.run_dir("run-missing-manifest"), "run-missing-manifest", identity
    )
    manifest_path = paths.run_dir("run-missing-manifest") / MANIFEST_FILE_NAME
    manifest_path.unlink()
    with pytest.raises(RunManifestError, match="has no valid manifest"):
        create_or_validate_manifest(
            paths.run_dir("run-missing-manifest"), "run-missing-manifest", identity
        )


def test_a_corrupt_manifest_is_refused(
    paths: ProjectPaths, catalog_plan: CatalogPlan
) -> None:
    create_or_validate_manifest(
        paths.run_dir("run-corrupt"),
        "run-corrupt",
        _make_identity(catalog_plan, paths, "fixture", ("fix-a",)),
    )
    manifest_path = paths.run_dir("run-corrupt") / MANIFEST_FILE_NAME
    manifest_path.write_bytes(b"not-json")
    with pytest.raises(RunManifestError, match="has no valid manifest"):
        create_or_validate_manifest(
            paths.run_dir("run-corrupt"),
            "run-corrupt",
            _make_identity(catalog_plan, paths, "fixture", ("fix-a",)),
        )


def test_a_deleted_manifest_in_a_pre_existing_run_is_refused(
    paths: ProjectPaths, catalog_plan: CatalogPlan
) -> None:
    identity = _make_identity(catalog_plan, paths, "fixture", ("fix-a",))
    create_or_validate_manifest(
        paths.run_dir("run-delete-manifest"), "run-delete-manifest", identity
    )
    manifest = paths.run_dir("run-delete-manifest") / MANIFEST_FILE_NAME
    manifest.unlink()
    with pytest.raises(RunManifestError, match="has no valid manifest"):
        create_or_validate_manifest(
            paths.run_dir("run-delete-manifest"), "run-delete-manifest", identity
        )


def test_selection_fingerprint_is_verified_on_reader_construction(
    era_plan_dir: Path,
) -> None:
    """The reader must refuse a bundle whose plan file no longer matches its locators."""
    from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME
    from edgar_sec.foundation.serialization import canonical_json

    plan = CatalogPlan(era_plan_dir, chunk_size=3)
    plan_path = era_plan_dir / PLAN_FILE_NAME
    original = plan_path.read_bytes()
    data = json.loads(original)
    data["plan_fingerprint"] = "0" * len(data["plan_fingerprint"])
    plan_path.write_bytes(canonical_json(data).encode("utf-8"))
    try:
        with pytest.raises(CatalogPlanError, match="fingerprint does not match"):
            CatalogPlan(era_plan_dir, chunk_size=3)
    finally:
        plan_path.write_bytes(original)


def test_manifest_excludes_non_work_order_plan_artifacts(
    paths: ProjectPaths, catalog_plan: CatalogPlan
) -> None:
    identity = _make_identity(catalog_plan, paths, "fixture", ("fix-a",))
    sources = identity.values["sources"]
    paths_by_kind = [s["path"] for s in sources]
    assert paths_by_kind[0] == "plan.json"
    assert paths_by_kind[1] == "locator_groups.parquet"
    assert all(s["sha256"] for s in sources)
    assert any(p.startswith("targets/") for p in paths_by_kind)
    assert all(p.endswith(".parquet") for p in paths_by_kind[1:])
    assert not any("reserve" in p for p in paths_by_kind)
