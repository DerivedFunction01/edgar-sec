from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.filing_catalog.schemas import (
    TARGET_PLAN_SCHEMA_VERSION,
    TARGET_SCHEMA,
)
from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.pipelines.document_planning.discovery import read_published_plan
from edgar_sec.pipelines.document_planning.inventory_evidence import (
    CatalogAccessionScopeRow,
    InventoryEvidenceError,
    InventoryEvidenceRow,
)
from edgar_sec.pipelines.document_planning.paths import (
    resolve_catalog_paths,
    resolve_document_planning_paths,
)
from edgar_sec.pipelines.document_planning.planner import (
    DocumentPlanningError,
    create_document_plan,
)
from edgar_sec.pipelines.document_planning.schemas import (
    PLAN_BUNDLE_SCHEMA_VERSION,
    TARGET_SCHEMA as PLAN_SCHEMA,
)

_ACCESSION = "0000000001-24-000001"
_ARCHIVE_ACCESSION = "000000000124000001"


def _paths(tmp_path: Path):
    return resolve_document_planning_paths(tmp_path, tmp_path / "artifacts")


def _write_profile(paths, targets: list[dict[str, Any]]) -> None:
    paths.profiles_root.mkdir(parents=True, exist_ok=True)
    profile = {
        "profile_id": "test-profile",
        "schema_version": "1",
        "version": "1",
        "rules": [{"form_selector": "*", "targets": targets}],
    }
    (paths.profiles_root / "test-profile.json").write_text(
        json.dumps(profile), encoding="utf-8"
    )


def _catalog_row(**changes: Any) -> dict[str, Any]:
    row = {
        "occurrence_id": "occ-1",
        "document_locator_key": "locator-1",
        "source_cik": "0000000001",
        "accession": _ARCHIVE_ACCESSION,
        "form": "10-K",
        "filing_date": "2024-01-02",
        "report_date": None,
        "primary_document": "primary.htm",
        "document_path": "primary.htm",
        "archive_url": f"https://www.sec.gov/Archives/edgar/data/1/{_ARCHIVE_ACCESSION}/primary.htm",
        "document_path_source": "primary_document",
        "reported_size": 100,
        "is_xbrl": True,
        "is_inline_xbrl": False,
        "is_xbrl_numeric": True,
    }
    row.update(changes)
    return row


def _publish_catalog(paths, rows: list[dict[str, Any]] | None = None) -> None:
    selected = rows or [_catalog_row()]
    catalog_paths = resolve_catalog_paths(paths.artifacts_root)
    root = catalog_paths.plan_dir("catalog-plan")
    part = root / "targets" / "form=10-K" / "data.parquet"
    part.parent.mkdir(parents=True)
    table = pa.Table.from_pylist(selected, schema=TARGET_SCHEMA)
    pq.write_table(table, part, compression="zstd")
    manifest = {
        "plan_id": "catalog-plan",
        "plan_schema_version": TARGET_PLAN_SCHEMA_VERSION,
        "catalog_id": "catalog-snapshot",
        "scope": "deterministic",
        "plan_fingerprint": "catalog-fingerprint",
        "forms": [],
        "counts": {"10-K": len(selected)},
        "selected_rows": len(selected),
        "target_parts": [
            {
                "form": "10-K",
                "path": "targets/form=10-K/data.parquet",
                "row_count": len(selected),
                "byte_size": part.stat().st_size,
                "sha256": file_sha256(part),
            }
        ],
    }
    (root / "plan.json").write_text(json.dumps(manifest), encoding="utf-8")


def _target(
    role: str,
    target_type: str,
    *,
    optional: bool = False,
    operations: list[str] | None = None,
    catalog_direct_selection: str | None = None,
):
    result: dict[str, Any] = {"role": role, "type": target_type, "optional": optional}
    if role == "primary" and catalog_direct_selection is not None:
        result["catalog_direct_selection"] = catalog_direct_selection
    if operations is not None:
        result["acquisition_policy"] = {"operations": operations}
    return result


def _parts(manifest: dict[str, Any], relation: str) -> list[dict[str, Any]]:
    return [part for part in manifest["parts"] if part["relation"] == relation]


def _relation_rows(plan, relation: str) -> list[dict[str, Any]]:
    return [
        row
        for part in _parts(plan.manifest, relation)
        for row in pq.read_table(plan.root / part["path"]).to_pylist()
    ]


def test_catalog_only_plan_is_pinned_sorted_and_identically_reused(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    _write_profile(
        paths,
        [_target("primary", "primary")],
    )
    _publish_catalog(paths)

    first = create_document_plan("catalog-plan", "test-profile", paths=paths)
    second = create_document_plan("catalog-plan", "test-profile", paths=paths)
    validated = read_published_plan(first.plan_id, paths)
    target_part = _parts(validated.manifest, "targets")[0]
    target_path = validated.root / target_part["path"]
    target = pq.read_table(target_path, schema=PLAN_SCHEMA).to_pylist()[0]

    assert first.plan_id.startswith("dplan_")
    assert not first.reused
    assert second.reused
    assert first.manifest == second.manifest
    identity = first.manifest["plan_identity"]
    assert identity["bundle_schema_version"] == PLAN_BUNDLE_SCHEMA_VERSION
    assert identity["row_group_size"] == first.manifest["row_group_size"]
    assert first.manifest["bundle_schema_version"] == PLAN_BUNDLE_SCHEMA_VERSION
    assert first.plan_id == f"dplan_{sha256_text(canonical_json(identity))[:32]}"
    prior_identity = dict(identity)
    prior_identity.pop("bundle_schema_version")
    assert first.plan_id != f"dplan_{sha256_text(canonical_json(prior_identity))[:32]}"
    assert target_part["byte_size"] == target_path.stat().st_size
    assert target["accession"] == _ACCESSION
    assert target["status"] == "matched"
    assert target["source_origin"] == "catalog_direct"
    assert target["availability_evidence"] == "catalog_metadata"
    assert target["target_url"].endswith("/primary.htm")
    assert target["inventory_entry_id"] is None
    assert target["catalog_direct_selection"] is None
    assert first.manifest["relation_row_counts"] == {
        "targets": 1,
        "target_operations": 3,
        "source_requests": 1,
        "operation_inputs": 3,
    }
    assert first.manifest["requested_operation_counts"] == {
        "raw": 1,
        "render_to_txt": 1,
        "render_to_xml": 1,
    }
    assert first.manifest["default_candidate_operation_counts"] == {
        "render_to_txt": 1,
        "render_to_xml": 1,
    }
    operations = _relation_rows(validated, "target_operations")
    inputs = _relation_rows(validated, "operation_inputs")
    source = _relation_rows(validated, "source_requests")[0]
    by_operation = {row["operation"]: row for row in operations}
    assert by_operation["raw"]["requested"]
    assert by_operation["render_to_txt"]["request_mode"] == "default_candidate"
    assert by_operation["render_to_xml"]["request_mode"] == "default_candidate"
    assert len(inputs) == 3
    assert {row["source_request_id"] for row in inputs} == {source["source_request_id"]}
    assert source["canonical_path"] == "primary.htm"
    assert first.manifest["inventory_snapshot_id"] is None
    assert first.manifest["inventory_snapshot_digest"] is None


def test_form_parts_have_deterministic_row_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    _write_profile(
        paths,
        [_target("primary", "primary")],
    )
    accessions = [f"00000000012400000{number}" for number in (1, 2, 3)]
    rows = [
        _catalog_row(
            occurrence_id=f"occ-{index}",
            accession=accession,
            document_locator_key=f"locator-{index}",
            archive_url=f"https://www.sec.gov/Archives/edgar/data/1/{accession}/primary.htm",
        )
        for index, accession in enumerate(accessions)
    ]
    _publish_catalog(paths, rows)
    monkeypatch.setenv("PARQUET_ROW_GROUP_SIZE", "2")

    result = create_document_plan("catalog-plan", "test-profile", paths=paths)
    monkeypatch.setenv("PARQUET_ROW_GROUP_SIZE", "3")
    validated = read_published_plan(result.plan_id, paths)

    target_parts = _parts(result.manifest, "targets")
    assert [part["rows"] for part in target_parts] == [2, 1]
    assert validated.manifest["row_group_size"] == 2
    assert [part["path"].rsplit("/", 1)[-1] for part in target_parts] == [
        "part-00000.parquet",
        "part-00001.parquet",
    ]


class _Evidence:
    snapshot_id = "snapshot-1"
    snapshot_digest = "a" * 64

    def __init__(self, *, indexed: bool, mismatch: bool = False) -> None:
        self.indexed = indexed
        self.mismatch = mismatch

    def stream(self, accessions):
        for request in accessions:
            assert isinstance(request, CatalogAccessionScopeRow)
            if self.mismatch:
                raise InventoryEvidenceError("inventory facts disagree with catalog")
            if not self.indexed:
                yield InventoryEvidenceRow(
                    _ACCESSION,
                    request.form,
                    request.filing_date,
                    False,
                    None,
                    None,
                )
                continue
            accession_row = {
                "accession": _ACCESSION,
                "filing_cik": "0000000001",
                "form": "10-K",
                "filing_date": "2024-01-02",
                "bundle_url": f"https://www.sec.gov/Archives/edgar/data/1/{_ARCHIVE_ACCESSION}/{_ACCESSION}.txt",
            }
            entries = [
                {
                    "entry_id": "entry-primary",
                    "table_kind": "document_format",
                    "document_type": "10-K",
                    "sequence": 1,
                    "byte_size": 200,
                    "archive_url": f"https://www.sec.gov/Archives/edgar/data/1/{_ARCHIVE_ACCESSION}/primary.htm",
                },
                {
                    "entry_id": "entry-exhibit",
                    "table_kind": "document_format",
                    "document_type": "EX-21",
                    "sequence": 2,
                    "byte_size": 50,
                    "archive_url": None,
                    "href": None,
                },
                {
                    "entry_id": "entry-xbrl",
                    "table_kind": "data_file",
                    "document_type": "XML",
                    "description": "EXTRACTED XBRL INSTANCE DOCUMENT",
                    "sequence": 1,
                    "byte_size": 300,
                    "archive_url": f"https://www.sec.gov/Archives/edgar/data/1/{_ARCHIVE_ACCESSION}/Financial_Report.xlsx",
                },
            ]
            for entry in entries:
                yield InventoryEvidenceRow(
                    _ACCESSION,
                    request.form,
                    request.filing_date,
                    True,
                    accession_row,
                    entry,
                )


def test_inventory_plan_uses_pinned_index_and_distinguishes_package_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    _write_profile(
        paths,
        [
            _target("primary", "primary"),
            _target("exhibit", "EX-21"),
            _target("data_file", "extracted_xbrl_instance"),
            _target("package", "xbrl_zip", optional=True),
        ],
    )
    _publish_catalog(paths)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_planning.planner._open_inventory",
        lambda _snapshot_id, _paths: _Evidence(indexed=True),
    )

    result = create_document_plan("catalog-plan", "test-profile", "snapshot-1", paths)
    plan = read_published_plan(result.plan_id, paths)
    rows = []
    for part in _parts(plan.manifest, "targets"):
        rows.extend(pq.read_table(plan.root / part["path"]).to_pylist())
    by_role = {row["target_role"]: row for row in rows}

    assert by_role["primary"]["source_origin"] == "inventory_index"
    assert by_role["primary"]["status"] == "matched"
    assert by_role["exhibit"]["retrieval_mode"] == "bundle_sequence"
    assert by_role["exhibit"]["sequence"] == 2
    assert by_role["data_file"]["status"] == "matched"
    assert by_role["package"]["status"] == "constructed_candidate"
    assert by_role["package"]["target_url"].endswith("-xbrl.zip")
    assert by_role["package"]["availability_evidence"] == "constructed"
    assert result.manifest["distinct_accession_coverage"]["inventory_indexed"] == 1


def test_explicit_policy_preserves_intent_and_cannot_suppress_raw(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    _write_profile(
        paths,
        [_target("primary", "primary", operations=["render_to_xml"])],
    )
    _publish_catalog(paths)

    result = create_document_plan("catalog-plan", "test-profile", paths=paths)
    plan = read_published_plan(result.plan_id, paths)
    by_operation = {
        row["operation"]: row for row in _relation_rows(plan, "target_operations")
    }
    inputs = _relation_rows(plan, "operation_inputs")

    assert by_operation["raw"]["requested"]
    assert by_operation["raw"]["request_mode"] == "mandatory_raw"
    assert by_operation["render_to_txt"]["requested"] is False
    assert by_operation["render_to_txt"]["request_mode"] == "not_requested"
    assert by_operation["render_to_xml"]["requested"] is True
    assert by_operation["render_to_xml"]["request_mode"] == "profile"
    assert len(inputs) == 2
    assert result.manifest["requested_operation_counts"] == {
        "raw": 1,
        "render_to_xml": 1,
    }
    assert result.manifest["unrequested_operation_counts"] == {"render_to_txt": 1}


def test_corrupt_target_part_size_is_rejected(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_profile(
        paths,
        [_target("primary", "primary")],
    )
    _publish_catalog(paths)
    result = create_document_plan("catalog-plan", "test-profile", paths=paths)
    manifest_path = paths.plan_manifest_path(result.plan_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _parts(manifest, "targets")[0]["byte_size"] += 1
    manifest["plan_digest"] = canonical_hash(
        {key: value for key, value in manifest.items() if key != "plan_digest"}
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="byte size mismatch"):
        read_published_plan(result.plan_id, paths)


@pytest.mark.parametrize("mismatch", [False, True])
def test_unindexed_is_unresolved_and_catalog_mismatch_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: bool,
) -> None:
    paths = _paths(tmp_path)
    _write_profile(
        paths,
        [_target("primary", "primary", optional=True)],
    )
    _publish_catalog(paths)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_planning.planner._open_inventory",
        lambda _snapshot_id, _paths: _Evidence(indexed=False, mismatch=mismatch),
    )

    if mismatch:
        with pytest.raises(DocumentPlanningError, match="inventory facts disagree"):
            create_document_plan("catalog-plan", "test-profile", "snapshot-1", paths)
        return

    result = create_document_plan("catalog-plan", "test-profile", "snapshot-1", paths)
    plan = read_published_plan(result.plan_id, paths)
    target = pq.read_table(
        plan.root / _parts(plan.manifest, "targets")[0]["path"]
    ).to_pylist()[0]

    assert target["status"] == "unresolved"
    assert target["status_reason"] == "accession_not_indexed"
    assert target["source_origin"] == "inventory_index"
    assert target["availability_evidence"] == "none"
